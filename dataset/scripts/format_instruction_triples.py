"""
Phase 2, Step 2.2 — Format CodeSearchNet samples as Gemma 3 instruction triples.
Run from repo root: python finetune/scripts/format_instruction_triples.py
Input:  finetune/data/raw/codesearchnet_filtered.jsonl
Output: finetune/data/processed/summarization_triples.jsonl
"""

import json
from pathlib import Path

INPUT_PATH  = Path("finetune/data/raw/codesearchnet_filtered.jsonl")
OUTPUT_PATH = Path("finetune/data/processed/summarization_triples.jsonl")

SYSTEM_PROMPT = (
    "You are a code summarizer. Given a function or code snippet, "
    "produce a clear, concise plain-English summary of what it does. "
    "Do not describe the syntax — explain the purpose and behavior."
)


def build_triple(code: str, docstring: str, language: str) -> dict:
    return {
        "system_prompt": SYSTEM_PROMPT,
        "user_input": f"Summarize this {language} function:\n\n```{language}\n{code}\n```",
        "assistant_output": docstring,
    }


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"{INPUT_PATH} not found. Run finetune/scripts/download_codesearchnet.py first."
        )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    with open(INPUT_PATH, "r", encoding="utf-8") as in_f, \
         open(OUTPUT_PATH, "w", encoding="utf-8") as out_f:
        for line in in_f:
            row = json.loads(line)
            code      = row.get("code", "").strip()
            docstring = row.get("docstring", "").strip()
            language  = row.get("language", "code")

            if len(code) < 30 or len(docstring) < 10 or len(code) > 3000:
                skipped += 1
                continue

            triple = build_triple(code, docstring, language)
            out_f.write(json.dumps(triple, ensure_ascii=False) + "\n")
            written += 1

    print(f"Done. Written: {written:,} | Skipped: {skipped:,} → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
