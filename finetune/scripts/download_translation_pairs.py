"""
Phase 2, Step 2.3 — Build cross-language translation dataset.
Sources:
  1. code_x_glue_cc_code_to_code_trans (HuggingFace) — Python <-> Java parallel corpus
  2. finetune/data/raw/manual_translations.jsonl (hand-crafted pairs, if it exists)
Run from repo root: python finetune/scripts/download_translation_pairs.py
Output: finetune/data/processed/translation_triples.jsonl
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

HF_TOKEN    = os.getenv("HF_TOKEN")
DATASET_NAME = "code_x_glue_cc_code_to_code_trans"
MANUAL_PATH  = Path("finetune/data/raw/manual_translations.jsonl")
OUTPUT_PATH  = Path("finetune/data/processed/translation_triples.jsonl")

SYSTEM_PROMPT = (
    "You are a code translator. Convert the given code to the target language "
    "while preserving logic and semantics. Use idiomatic style for the target language — "
    "do not just transliterate syntax. Add a short comment where the translation is non-obvious."
)


def build_triple(source_lang: str, target_lang: str, source_code: str, target_code: str) -> dict:
    return {
        "system_prompt": SYSTEM_PROMPT,
        "user_input": (
            f"Convert this {source_lang} code to {target_lang}:\n\n"
            f"```{source_lang.lower()}\n{source_code.strip()}\n```"
        ),
        "assistant_output": f"```{target_lang.lower()}\n{target_code.strip()}\n```",
    }


def load_hf_pairs() -> list[dict]:
    from datasets import load_dataset

    triples = []
    print(f"Loading {DATASET_NAME} from HuggingFace...")
    try:
        ds = load_dataset(
            DATASET_NAME,
            split="train+validation+test",
            token=HF_TOKEN,
            trust_remote_code=True,
        )
        for row in ds:
            java   = (row.get("java") or "").strip()
            python = (row.get("python") or "").strip()
            if not java or not python:
                continue
            triples.append(build_triple("Java", "Python", java, python))
            triples.append(build_triple("Python", "Java", python, java))
        print(f"  Loaded {len(triples):,} pairs (both directions)")
    except Exception as e:
        print(f"  WARNING: Could not load HuggingFace dataset: {e}")
        print("  Continuing with manual pairs only.")

    return triples


def load_manual_pairs() -> list[dict]:
    if not MANUAL_PATH.exists():
        print(f"  No manual pairs at {MANUAL_PATH} — skipping.")
        return []

    triples = []
    with open(MANUAL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if all(k in row for k in ("system_prompt", "user_input", "assistant_output")):
                triples.append(row)

    print(f"  Manual pairs loaded: {len(triples):,}")
    return triples


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    hf_triples     = load_hf_pairs()
    manual_triples = load_manual_pairs()
    all_triples    = hf_triples + manual_triples

    print(f"\nTotal translation triples: {len(all_triples):,}")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for triple in all_triples:
            f.write(json.dumps(triple, ensure_ascii=False) + "\n")

    print(f"Done → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
