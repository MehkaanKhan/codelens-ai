"""
Phase 2, Step 2.4 — Mix summarization + translation at 70/30 and split 80/10/10.
Run from repo root:
  python finetune/scripts/mix_and_split_dataset.py            # write files
  python finetune/scripts/mix_and_split_dataset.py --verify   # stats only
Outputs: finetune/data/processed/train.jsonl, val.jsonl, test.jsonl
"""

import json
import random
import sys
from pathlib import Path

SUMMARIZATION_PATH = Path("finetune/data/processed/summarization_triples.jsonl")
TRANSLATION_PATH   = Path("finetune/data/processed/translation_triples.jsonl")
OUTPUT_DIR         = Path("finetune/data/processed")

SUMMARIZATION_RATIO = 0.70
TRANSLATION_RATIO   = 0.30
TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
SEED = 42


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def mix(summ: list[dict], trans: list[dict]) -> list[dict]:
    needed_summ = int(len(trans) * (SUMMARIZATION_RATIO / TRANSLATION_RATIO))
    if needed_summ <= len(summ):
        sampled_summ  = random.sample(summ, needed_summ)
        sampled_trans = trans
    else:
        sampled_summ  = summ
        needed_trans  = int(len(summ) * (TRANSLATION_RATIO / SUMMARIZATION_RATIO))
        sampled_trans = random.sample(trans, min(needed_trans, len(trans)))

    mixed = sampled_summ + sampled_trans
    random.shuffle(mixed)
    return mixed


def split(data: list[dict]) -> tuple[list, list, list]:
    n = len(data)
    train_end = int(n * TRAIN_RATIO)
    val_end   = train_end + int(n * VAL_RATIO)
    return data[:train_end], data[train_end:val_end], data[val_end:]


def write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    verify_only = "--verify" in sys.argv
    random.seed(SEED)

    print("Loading datasets...")
    summ  = load_jsonl(SUMMARIZATION_PATH)
    trans = load_jsonl(TRANSLATION_PATH)
    print(f"  Summarization : {len(summ):,}")
    print(f"  Translation   : {len(trans):,}")

    mixed = mix(summ, trans)
    train, val, test = split(mixed)

    summ_in_train  = sum(1 for r in train if "Summarize" in r.get("user_input", ""))
    trans_in_train = len(train) - summ_in_train

    print(f"\nMixed total : {len(mixed):,}")
    print(f"  Train : {len(train):,}  ({len(train)/len(mixed)*100:.1f}%)")
    print(f"  Val   : {len(val):,}  ({len(val)/len(mixed)*100:.1f}%)")
    print(f"  Test  : {len(test):,}  ({len(test)/len(mixed)*100:.1f}%)")
    print(f"\nTrain task split:")
    print(f"  Summarization : {summ_in_train:,}  ({summ_in_train/len(train)*100:.1f}%)")
    print(f"  Translation   : {trans_in_train:,}  ({trans_in_train/len(train)*100:.1f}%)")

    if verify_only:
        print("\n[--verify] No files written.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUTPUT_DIR / "train.jsonl", train)
    write_jsonl(OUTPUT_DIR / "val.jsonl",   val)
    write_jsonl(OUTPUT_DIR / "test.jsonl",  test)
    print(f"\nSaved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
