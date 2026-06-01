"""
CodeLens AI — Merge + GGUF Export (run this after training is done)
Skips training entirely. Uses checkpoint-200 adapter.
Run: python -X utf8 finetune/merge_and_export.py
CPU-only — no GPU required.
"""

import os, gc, sys, subprocess, shutil, zipfile, io, stat, pathlib

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.resolve()
CHECKPOINT   = str(PROJECT_ROOT / 'finetune' / 'output' / 'adapter' / 'checkpoint-200')
MERGED_DIR   = str(PROJECT_ROOT / 'finetune' / 'output' / 'merged')
GGUF_PATH    = str(PROJECT_ROOT / 'codelens-qwen-q4_k_m.gguf')
LLAMA_DIR    = str(PROJECT_ROOT / 'finetune' / 'llama.cpp')

BASE_MODEL   = 'Qwen/Qwen2.5-Coder-3B-Instruct'

import torch

def merge():
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if os.path.exists(MERGED_DIR) and os.path.exists(os.path.join(MERGED_DIR, 'model.safetensors')):
        print(f'Merged model already exists at {MERGED_DIR} — skipping merge.')
        tokenizer = AutoTokenizer.from_pretrained(MERGED_DIR)
        return tokenizer

    print(f'Loading base model {BASE_MODEL} on CPU (float16)...')
    print('This needs ~6 GB RAM and takes ~5 min — do not close the terminal.\n')
    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map='cpu',
        low_cpu_mem_usage=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

    print(f'Loading LoRA adapter from {CHECKPOINT}...')
    base = PeftModel.from_pretrained(base, CHECKPOINT)

    print('Merging weights...')
    base = base.merge_and_unload()

    os.makedirs(MERGED_DIR, exist_ok=True)
    print(f'Saving merged model to {MERGED_DIR}...')
    base.save_pretrained(MERGED_DIR, safe_serialization=True)
    tokenizer.save_pretrained(MERGED_DIR)

    del base
    gc.collect()
    print('Merge complete.\n')
    return tokenizer


def export_gguf():
    import requests

    if os.path.exists(GGUF_PATH):
        print(f'GGUF already exists: {GGUF_PATH}')
        print(f'Size: {os.path.getsize(GGUF_PATH) / 1e9:.2f} GB')
        return

    # Clone llama.cpp for Python conversion scripts
    if not os.path.exists(LLAMA_DIR):
        print('Cloning llama.cpp...')
        subprocess.run(['git', 'clone', 'https://github.com/ggerganov/llama.cpp',
                        '--depth=1', LLAMA_DIR], check=True)

    req_file = os.path.join(LLAMA_DIR, 'requirements.txt')
    if os.path.exists(req_file):
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', req_file], check=False)

    f16_path = str(PROJECT_ROOT / 'finetune' / 'output' / 'codelens-qwen-f16.gguf')
    convert_script = os.path.join(LLAMA_DIR, 'convert_hf_to_gguf.py')

    print('Converting to GGUF f16... (5-10 min)')
    subprocess.run([sys.executable, convert_script, MERGED_DIR,
                    '--outfile', f16_path, '--outtype', 'f16'], check=True)
    print(f'F16 GGUF: {os.path.getsize(f16_path) / 1e9:.1f} GB')

    # Download pre-built Windows quantize binary
    quantize_bin = None
    try:
        print('Downloading llama-quantize for Windows...')
        rel = requests.get(
            'https://api.github.com/repos/ggerganov/llama.cpp/releases/latest',
            timeout=30
        ).json()
        asset_url = None
        for asset in rel.get('assets', []):
            name = asset['name']
            if 'win' in name.lower() and 'x64' in name.lower() and name.endswith('.zip'):
                if 'cuda' in name.lower() or 'cu12' in name.lower():
                    asset_url = asset['browser_download_url']
                    print(f'Downloading: {name}')
                    break
        if not asset_url:
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
                (n for n in z.namelist() if 'llama-quantize' in n and n.endswith('.exe')), None
            )
            if exe_name:
                bin_path = str(PROJECT_ROOT / 'finetune' / 'llama-quantize.exe')
                with open(bin_path, 'wb') as bf:
                    bf.write(z.read(exe_name))
                quantize_bin = bin_path
                print('llama-quantize.exe ready.')
    except Exception as e:
        print(f'Could not get quantize binary: {e}')

    if quantize_bin and os.path.exists(quantize_bin):
        print('Quantizing to Q4_K_M...')
        subprocess.run([quantize_bin, f16_path, GGUF_PATH, 'Q4_K_M'], check=True)
        os.remove(f16_path)
    else:
        shutil.move(f16_path, GGUF_PATH)
        print('No quantize binary — saved as f16 (larger but works with Ollama).')

    print(f'GGUF saved: {GGUF_PATH}')
    print(f'Size: {os.path.getsize(GGUF_PATH) / 1e9:.2f} GB\n')


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

    print('=' * 60)
    print('DONE. Run these commands to register with Ollama:')
    print('=' * 60)
    print()
    print(f'  cd C:\\Users\\User\\codelens-ai')
    print(f'  ollama create codelens-qwen -f Modelfile')
    print()
    print('  ollama run codelens-qwen')
    print('  >>> Summarize this: def f(x): return x * 2')
    print('=' * 60)


if __name__ == '__main__':
    print('=== CodeLens AI — Merge & Export ===\n')
    print(f'Adapter : {CHECKPOINT}')
    print(f'Output  : {GGUF_PATH}\n')

    if not os.path.exists(CHECKPOINT):
        raise FileNotFoundError(f'Checkpoint not found: {CHECKPOINT}')

    merge()
    export_gguf()
    write_modelfile()
