"""
Embed code chunks using nomic-embed-text via Ollama.
Output: .tmp/chunks_with_embeddings.jsonl

Usage: python tools/embed_chunks.py [--input .tmp/chunks.jsonl] [--output .tmp/chunks_with_embeddings.jsonl] [--batch-size 50]
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Always resolve .tmp relative to repo root regardless of CWD
_REPO_ROOT    = Path(__file__).parent.parent.resolve()
_DEFAULT_IN   = str(_REPO_ROOT / ".tmp" / "chunks.jsonl")
_DEFAULT_OUT  = str(_REPO_ROOT / ".tmp" / "chunks_with_embeddings.jsonl")


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Send a batch of texts to Ollama's embed endpoint."""
    url = f"{OLLAMA_BASE_URL}/api/embed"
    response = requests.post(url, json={"model": EMBED_MODEL, "input": texts}, timeout=120)
    response.raise_for_status()
    return response.json()["embeddings"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default=_DEFAULT_IN)
    parser.add_argument("--output", default=_DEFAULT_OUT)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    chunks = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))

    print(f"Embedding {len(chunks)} chunks with {EMBED_MODEL}...")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", encoding="utf-8") as out_f:
        for i in range(0, len(chunks), args.batch_size):
            batch = chunks[i:i + args.batch_size]
            texts = [c["code"][:2000] for c in batch]  # truncate to avoid token limits

            try:
                embeddings = embed_batch(texts)
            except Exception as e:
                print(f"  Batch {i//args.batch_size + 1} failed: {e}. Retrying with batch_size=1...")
                embeddings = []
                for text in texts:
                    try:
                        emb = embed_batch([text])
                        embeddings.extend(emb)
                        time.sleep(0.1)
                    except Exception as inner_e:
                        print(f"  Single embed failed: {inner_e}. Skipping.")
                        embeddings.append([])

            for chunk, embedding in zip(batch, embeddings):
                chunk["embedding"] = embedding
                out_f.write(json.dumps(chunk) + "\n")

            done = min(i + args.batch_size, len(chunks))
            print(f"  {done}/{len(chunks)} chunks embedded")

    print(f"Done. Output: {output}")


if __name__ == "__main__":
    main()
