"""
CodeLens AI — Local QLoRA Fine-Tuning
Run: python finetune/train_local.py
Requires: RTX GPU with 8+ GB VRAM, ~16 GB RAM
"""

import os, gc, sys, subprocess, shutil, zipfile, io, stat, pathlib

# ── CONFIG — edit these paths if needed ──────────────────────────────────────
TRAIN_FILE = r'C:\Users\User\Downloads\drive-download-20260519T060515Z-3-002\train.jsonl'
VAL_FILE   = r'C:\Users\User\Downloads\drive-download-20260519T060515Z-3-002\val.jsonl'

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()
OUTPUT_DIR   = str(PROJECT_ROOT / 'finetune' / 'output' / 'adapter')
MERGED_DIR   = str(PROJECT_ROOT / 'finetune' / 'output' / 'merged')
GGUF_PATH    = str(PROJECT_ROOT / 'codelens-qwen-q4_k_m.gguf')
LLAMA_DIR    = str(PROJECT_ROOT / 'finetune' / 'llama.cpp')

BASE_MODEL  = 'Qwen/Qwen2.5-Coder-3B-Instruct'

LORA_R         = 16
LORA_ALPHA     = 32
LORA_DROPOUT   = 0.05
TARGET_MODULES = ['q_proj', 'k_proj', 'v_proj', 'o_proj',
                  'gate_proj', 'up_proj', 'down_proj']

NUM_EPOCHS    = 1
BATCH_SIZE    = 2
GRAD_ACCUM    = 8
LR            = 2e-4
MAX_SEQ_LEN   = 1024
WARMUP_STEPS  = 100
LOGGING_STEPS = 10
EVAL_STEPS    = 200
SAVE_STEPS    = 200
TRAIN_SUBSET  = 15000
# ─────────────────────────────────────────────────────────────────────────────


def check_gpu():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('No CUDA GPU detected. Make sure you installed the CUDA version of PyTorch.')
    name = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    bf16 = torch.cuda.is_bf16_supported()
    print(f'GPU  : {name}')
    print(f'VRAM : {vram:.1f} GB')
    print(f'dtype: {"bfloat16" if bf16 else "float16"} (auto-detected)')
    return torch.bfloat16 if bf16 else torch.float16, bf16


def check_dataset():
    for p in [TRAIN_FILE, VAL_FILE]:
        if not os.path.exists(p):
            raise FileNotFoundError(
                f'Dataset file not found: {p}\n'
                'Edit TRAIN_FILE / VAL_FILE at the top of this script.'
            )
    print(f'train.jsonl : {os.path.getsize(TRAIN_FILE) // 1024 // 1024} MB')
    print(f'val.jsonl   : {os.path.getsize(VAL_FILE) // 1024 // 1024} MB')


def load_datasets(tokenizer):
    from datasets import load_dataset

    train_ds = load_dataset('json', data_files=TRAIN_FILE, split=f'train[:{TRAIN_SUBSET}]')
    val_ds   = load_dataset('json', data_files=VAL_FILE,   split='train')
    print(f'Train : {len(train_ds):,} samples')
    print(f'Val   : {len(val_ds):,} samples')

    required = {'system_prompt', 'user_input', 'assistant_output'}
    actual   = set(train_ds.features.keys())
    if not required.issubset(actual):
        raise ValueError(f'Missing fields: {required - actual}. Your dataset has: {actual}')

    def format_sample(sample):
        messages = [
            {'role': 'user',      'content': f"[SYSTEM]: {sample['system_prompt']}\n\n{sample['user_input']}"},
            {'role': 'assistant', 'content': sample['assistant_output']},
        ]
        return {'text': tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)}

    train_ds = train_ds.map(format_sample, remove_columns=train_ds.column_names)
    val_ds   = val_ds.map(format_sample,   remove_columns=val_ds.column_names)
    print('Dataset formatted.')
    return train_ds, val_ds


def load_model_and_tokenizer(compute_dtype):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token    = tokenizer.eos_token
    tokenizer.padding_side = 'right'

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type='nf4',
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=True,
    )

    print(f'Loading {BASE_MODEL} in 4-bit...')
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map={'': 0},
        torch_dtype=compute_dtype,
        attn_implementation='sdpa',
    )
    model.config.use_cache      = False
    model.config.pretraining_tp = 1

    total = sum(p.numel() for p in model.parameters()) / 1e9
    print(f'Model loaded: {total:.1f}B parameters')
    return model, tokenizer


def apply_lora(model):
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    try:
        model = prepare_model_for_kbit_training(model)
    except Exception:
        model.enable_input_require_grads()

    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=TARGET_MODULES,
        bias='none',
        task_type='CAUSAL_LM',
    )
    model = get_peft_model(model, lora_config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total     = sum(p.numel() for p in model.parameters())
    print(f'LoRA: {trainable / 1e6:.1f}M trainable / {total / 1e9:.1f}B total ({100 * trainable / total:.2f}%)')
    return model


def train(model, tokenizer, train_ds, val_ds, use_bf16):
    import gc, torch
    from trl import SFTTrainer, SFTConfig

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    resume_path = None
    if os.path.exists(os.path.join(OUTPUT_DIR, 'trainer_state.json')):
        resume_path = OUTPUT_DIR
        print(f'Resuming from checkpoint: {OUTPUT_DIR}')

    def build_trainer(batch_size, grad_accum):
        config = SFTConfig(
            output_dir=OUTPUT_DIR,
            num_train_epochs=NUM_EPOCHS,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=grad_accum,
            learning_rate=LR,
            warmup_steps=WARMUP_STEPS,
            logging_steps=LOGGING_STEPS,
            eval_strategy='steps',
            eval_steps=EVAL_STEPS,
            save_strategy='steps',
            save_steps=SAVE_STEPS,
            save_total_limit=3,
            load_best_model_at_end=True,
            bf16=use_bf16,
            fp16=not use_bf16,
            gradient_checkpointing=True,
            gradient_checkpointing_kwargs={'use_reentrant': False},
            optim='paged_adamw_8bit',
            report_to='none',
            dataset_text_field='text',
            max_length=MAX_SEQ_LEN,
            packing=True,
            dataloader_pin_memory=False,
            dataloader_num_workers=0,  # 0 on Windows to avoid multiprocessing issues
        )
        return SFTTrainer(
            model=model,
            processing_class=tokenizer,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            args=config,
        )

    batch_size = BATCH_SIZE
    g_accum    = GRAD_ACCUM
    result     = None

    for attempt in range(3):
        try:
            print(f'\nTraining: batch_size={batch_size}, grad_accum={g_accum}')
            trainer = build_trainer(batch_size, g_accum)
            result  = trainer.train(resume_from_checkpoint=resume_path)
            break
        except torch.cuda.OutOfMemoryError:
            print(f'OOM at batch_size={batch_size} — halving...')
            gc.collect()
            torch.cuda.empty_cache()
            batch_size = max(1, batch_size // 2)
            g_accum    = g_accum * 2
            if attempt == 2:
                raise RuntimeError('OOM even at batch_size=1. Set MAX_SEQ_LEN=512 and retry.')

    print(f'\nTraining done! Loss: {result.training_loss:.4f}  Steps: {result.global_step}')
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f'Adapter saved: {OUTPUT_DIR}')
    return trainer


def merge_model(compute_dtype, tokenizer):
    import gc, torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    gc.collect()
    torch.cuda.empty_cache()

    print(f'\nLoading {BASE_MODEL} for merge (CPU)...')
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.float16, device_map='cpu')
    print('Loading adapter...')
    base = PeftModel.from_pretrained(base, OUTPUT_DIR)
    print('Merging...')
    base = base.merge_and_unload()
    os.makedirs(MERGED_DIR, exist_ok=True)
    print(f'Saving merged model to {MERGED_DIR}...')
    base.save_pretrained(MERGED_DIR, safe_serialization=True)
    tokenizer.save_pretrained(MERGED_DIR)
    print('Merge complete.')
    return base


def export_gguf():
    import requests

    # Step 1: clone llama.cpp for Python scripts
    if not os.path.exists(LLAMA_DIR):
        print('\nCloning llama.cpp...')
        subprocess.run(['git', 'clone', 'https://github.com/ggerganov/llama.cpp',
                        '--depth=1', LLAMA_DIR], check=True)

    req_file = os.path.join(LLAMA_DIR, 'requirements.txt')
    if os.path.exists(req_file):
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', req_file], check=False)

    # Step 2: convert to f16 GGUF
    f16_path = str(PROJECT_ROOT / 'finetune' / 'output' / 'codelens-qwen-f16.gguf')
    convert_script = os.path.join(LLAMA_DIR, 'convert_hf_to_gguf.py')
    print('\nConverting merged model to GGUF f16... (5-10 min)')
    subprocess.run([sys.executable, convert_script, MERGED_DIR,
                    '--outfile', f16_path, '--outtype', 'f16'], check=True)
    print(f'F16 GGUF: {os.path.getsize(f16_path) / 1e9:.1f} GB')

    # Step 3: download pre-built llama-quantize for Windows from GitHub Releases
    quantize_bin = None
    try:
        print('Fetching latest llama.cpp release for Windows...')
        rel = requests.get(
            'https://api.github.com/repos/ggerganov/llama.cpp/releases/latest',
            timeout=30
        ).json()
        asset_url = None
        for asset in rel.get('assets', []):
            name = asset['name']
            # prefer CUDA build for Windows x64
            if 'win' in name.lower() and 'x64' in name.lower() and name.endswith('.zip'):
                if 'cuda' in name.lower() or 'cu12' in name.lower():
                    asset_url = asset['browser_download_url']
                    print(f'Downloading: {name}')
                    break
        if not asset_url:
            # fallback: any windows x64 zip
            for asset in rel.get('assets', []):
                name = asset['name']
                if 'win' in name.lower() and 'x64' in name.lower() and name.endswith('.zip'):
                    asset_url = asset['browser_download_url']
                    print(f'Downloading: {name}')
                    break

        if asset_url:
            r = requests.get(asset_url, timeout=300)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            exe_name = next(
                (n for n in z.namelist() if 'llama-quantize' in n and n.endswith('.exe')),
                None
            )
            if exe_name:
                bin_path = str(PROJECT_ROOT / 'finetune' / 'llama-quantize.exe')
                with open(bin_path, 'wb') as bf:
                    bf.write(z.read(exe_name))
                quantize_bin = bin_path
                print('llama-quantize.exe ready.')
    except Exception as e:
        print(f'Could not get quantize binary: {e}')

    # Step 4: quantize to Q4_K_M or keep f16
    if quantize_bin and os.path.exists(quantize_bin):
        print('Quantizing to Q4_K_M...')
        subprocess.run([quantize_bin, f16_path, GGUF_PATH, 'Q4_K_M'], check=True)
        os.remove(f16_path)
        print(f'Q4_K_M GGUF: {GGUF_PATH}')
    else:
        shutil.move(f16_path, GGUF_PATH)
        print(f'Saved as f16 GGUF (no quantize binary): {GGUF_PATH}')

    print(f'Final size: {os.path.getsize(GGUF_PATH) / 1e9:.2f} GB')


def write_modelfile():
    modelfile_path = str(PROJECT_ROOT / 'Modelfile')
    content = f'''FROM {GGUF_PATH}

SYSTEM """You are CodeLens AI, an expert programming assistant specialized in code understanding and cross-language translation. You help developers understand unfamiliar codebases by providing clear, accurate explanations. When translating code between languages, preserve the intent and semantics, not just the syntax. Be concise and educational."""

PARAMETER temperature 0.1
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 4096
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
'''
    with open(modelfile_path, 'w') as f:
        f.write(content)
    print(f'\nModelfile saved: {modelfile_path}')
    print()
    print('=' * 60)
    print('NEXT STEPS — run these in a new terminal:')
    print('=' * 60)
    print()
    print('  ollama create codelens-qwen -f Modelfile')
    print()
    print('  ollama run codelens-qwen')
    print('  >>> Summarize this: def f(x): return x * 2')
    print()
    print('  ollama list')
    print('=' * 60)


if __name__ == '__main__':
    print('=== CodeLens AI — Local Fine-Tuning ===\n')

    compute_dtype, use_bf16 = check_gpu()
    check_dataset()

    model, tokenizer = load_model_and_tokenizer(compute_dtype)
    train_ds, val_ds = load_datasets(tokenizer)
    model            = apply_lora(model)

    trainer = train(model, tokenizer, train_ds, val_ds, use_bf16)

    del model, trainer
    gc.collect()

    import torch
    torch.cuda.empty_cache()

    merged = merge_model(compute_dtype, tokenizer)

    del merged
    gc.collect()

    export_gguf()
    write_modelfile()

    print('\nAll done!')
