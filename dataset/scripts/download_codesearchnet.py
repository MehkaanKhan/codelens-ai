"""
Phase 2, Step 2.1 -- Download and filter CodeSearchNet.
Dataset: code-search-net/code_search_net
Run from repo root: python finetune/scripts/download_codesearchnet.py
Output: finetune/data/raw/codesearchnet_filtered.jsonl
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

HF_TOKEN   = os.getenv("HF_TOKEN")
LANGUAGES  = ["python", "javascript", "java", "go", "php", "ruby"]
DATASET_ID = "code-search-net/code_search_net"
OUTPUT_PATH = Path("finetune/data/raw/codesearchnet_filtered.jsonl")


def main():
    from datasets import load_dataset

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    total_written = 0
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out_f:
        for lang in LANGUAGES:
            print(f"[{lang}] Loading...")
            try:
                ds = load_dataset(
                    DATASET_ID,
                    lang,
                    split="train+validation+test",
                    token=HF_TOKEN,
                )
            except Exception as e:
                print(f"[{lang}] FAILED: {e}")
                continue

            lang_count = 0
            for row in ds:
                code      = (row.get("func_code_string") or "").strip()
                docstring = (row.get("func_documentation_string") or "").strip()

                if not code or not docstring:
                    continue

                record = {
                    "language": lang,
                    "func_name": row.get("func_name", ""),
                    "code": code,
                    "docstring": docstring,
                }
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                lang_count += 1

            total_written += lang_count
            print(f"[{lang}] {lang_count:,} samples written")

    print(f"\nDone. Total: {total_written:,} samples -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
