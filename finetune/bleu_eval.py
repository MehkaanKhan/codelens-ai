"""
CodeLens AI — BLEU Evaluation (Phase 7)
Compares fine-tuned codelens-qwen vs base qwen2.5-coder:3b on val set.

Run: python -X utf8 finetune/bleu_eval.py
Requirements: pip install sacrebleu requests
"""

import json, os, time, pathlib, argparse
import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────
VAL_FILE       = r'C:\Users\User\Downloads\drive-download-20260519T060515Z-3-002\val.jsonl'
FINETUNED_MODEL = 'codelens-qwen'
BASE_MODEL      = 'qwen2.5-coder:3b'
OLLAMA_URL      = 'http://localhost:11434'
N_SAMPLES       = 100   # number of val examples to evaluate (keep small for speed)
MAX_NEW_TOKENS  = 256
OUTPUT_FILE     = str(pathlib.Path(__file__).parent / 'bleu_results.json')
# ─────────────────────────────────────────────────────────────────────────────


def load_val_samples(n: int) -> list[dict]:
    samples = []
    with open(VAL_FILE, encoding='utf-8') as f:
        for line in f:
            if len(samples) >= n:
                break
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    print(f'Loaded {len(samples)} validation samples.')
    return samples


def build_prompt(sample: dict) -> str:
    return f"[SYSTEM]: {sample['system_prompt']}\n\n{sample['user_input']}"


def generate(model: str, prompt: str) -> str:
    try:
        resp = requests.post(
            f'{OLLAMA_URL}/api/generate',
            json={'model': model, 'prompt': prompt, 'stream': False,
                  'options': {'num_predict': MAX_NEW_TOKENS, 'temperature': 0.1}},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get('response', '').strip()
    except Exception as e:
        print(f'  [!] Generation error: {e}')
        return ''


def corpus_bleu(hypotheses: list[str], references: list[str]) -> float:
    """Compute corpus-level BLEU-4 using sacrebleu."""
    import sacrebleu
    result = sacrebleu.corpus_bleu(hypotheses, [references])
    return result.score


def token_f1(hyp: str, ref: str) -> float:
    """Token-level F1 (precision & recall over unigrams)."""
    hyp_tokens = set(hyp.lower().split())
    ref_tokens = set(ref.lower().split())
    if not ref_tokens or not hyp_tokens:
        return 0.0
    precision = len(hyp_tokens & ref_tokens) / len(hyp_tokens)
    recall    = len(hyp_tokens & ref_tokens) / len(ref_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def evaluate(model: str, samples: list[dict], label: str) -> dict:
    print(f'\n=== Evaluating: {label} ===')
    hypotheses, references = [], []
    f1_scores = []

    for i, sample in enumerate(samples):
        prompt = build_prompt(sample)
        ref    = sample['assistant_output'].strip()

        hyp = generate(model, prompt)

        hypotheses.append(hyp if hyp else ' ')
        references.append(ref)
        f1_scores.append(token_f1(hyp, ref))

        if (i + 1) % 10 == 0:
            interim_bleu = corpus_bleu(hypotheses, references)
            interim_f1   = sum(f1_scores) / len(f1_scores)
            print(f'  [{i+1}/{len(samples)}] BLEU: {interim_bleu:.2f}  F1: {interim_f1:.3f}')

    bleu = corpus_bleu(hypotheses, references)
    f1   = sum(f1_scores) / len(f1_scores)
    print(f'\n{label} — Final BLEU: {bleu:.2f}  Token-F1: {f1:.3f}')
    return {'model': label, 'bleu': round(bleu, 4), 'token_f1': round(f1, 4),
            'n_samples': len(samples)}


def check_model(model: str) -> bool:
    try:
        resp = requests.get(f'{OLLAMA_URL}/api/tags', timeout=5)
        models = [m['name'] for m in resp.json().get('models', [])]
        return any(model in m for m in models)
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n', type=int, default=N_SAMPLES, help='Number of val samples')
    args = parser.parse_args()

    print('=== CodeLens AI — BLEU Evaluation ===\n')

    # Install sacrebleu if missing
    try:
        import sacrebleu
    except ImportError:
        print('Installing sacrebleu...')
        import subprocess, sys
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'sacrebleu', '-q'], check=True)

    # Check Ollama is running
    try:
        requests.get(f'{OLLAMA_URL}/api/tags', timeout=5)
    except Exception:
        raise RuntimeError('Ollama is not running. Start it with: ollama serve')

    # Check both models exist
    for model in [FINETUNED_MODEL, BASE_MODEL]:
        if not check_model(model):
            raise RuntimeError(
                f'Model "{model}" not found in Ollama.\n'
                f'Run: ollama pull {model}' if model == BASE_MODEL
                else f'Run: ollama create codelens-qwen -f Modelfile'
            )

    samples = load_val_samples(args.n)

    t0 = time.time()
    finetuned_result = evaluate(FINETUNED_MODEL, samples, f'Fine-tuned ({FINETUNED_MODEL})')
    base_result      = evaluate(BASE_MODEL,      samples, f'Base ({BASE_MODEL})')
    elapsed = time.time() - t0

    # Summary
    bleu_delta = finetuned_result['bleu'] - base_result['bleu']
    f1_delta   = finetuned_result['token_f1'] - base_result['token_f1']

    print('\n' + '=' * 55)
    print('RESULTS SUMMARY')
    print('=' * 55)
    print(f"{'Model':<30} {'BLEU':>8} {'Token-F1':>10}")
    print('-' * 55)
    print(f"{'Fine-tuned (codelens-qwen)':<30} {finetuned_result['bleu']:>8.2f} {finetuned_result['token_f1']:>10.3f}")
    print(f"{'Base (qwen2.5-coder:3b)':<30} {base_result['bleu']:>8.2f} {base_result['token_f1']:>10.3f}")
    print('-' * 55)
    delta_sign = '+' if bleu_delta >= 0 else ''
    print(f"{'Delta':<30} {delta_sign}{bleu_delta:>7.2f} {delta_sign}{f1_delta:>9.3f}")
    print('=' * 55)
    print(f'Total time: {elapsed/60:.1f} min  |  Samples: {len(samples)}')

    results = {
        'finetuned': finetuned_result,
        'base':      base_result,
        'delta':     {'bleu': round(bleu_delta, 4), 'token_f1': round(f1_delta, 4)},
        'n_samples': len(samples),
        'elapsed_min': round(elapsed / 60, 2),
    }
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    print(f'\nResults saved to: {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
