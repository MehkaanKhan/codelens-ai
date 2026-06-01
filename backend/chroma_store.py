"""
Store and retrieve code chunk embeddings in ChromaDB.

Usage:
  python tools/chroma_store.py --action store [--input .tmp/chunks_with_embeddings.jsonl]
  python tools/chroma_store.py --action query --query "authentication logic" --top-k 5
  python tools/chroma_store.py --action clear
  python tools/chroma_store.py --action status
"""

import argparse
import json
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv

load_dotenv()

# ── Path resolution ────────────────────────────────────────────────────────────
# Resolve .tmp relative to the repo root (parent of tools/) so it always works
# regardless of the current working directory.
_REPO_ROOT = Path(__file__).parent.parent.resolve()
_DEFAULT_PERSIST = str(_REPO_ROOT / ".tmp" / "chromadb")
_DEFAULT_INPUT   = str(_REPO_ROOT / ".tmp" / "chunks_with_embeddings.jsonl")

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", _DEFAULT_PERSIST)
COLLECTION_NAME = "codelens_chunks"


def get_client():
    Path(CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def store(input_path: str = _DEFAULT_INPUT):
    client = get_client()

    # Drop existing collection to avoid duplicates on re-index
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    chunks = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))

    # Filter out chunks with empty embeddings
    valid = [c for c in chunks if c.get("embedding")]
    print(f"Storing {len(valid)}/{len(chunks)} chunks in ChromaDB...")

    batch_size = 500
    for i in range(0, len(valid), batch_size):
        batch = valid[i:i + batch_size]
        collection.add(
            ids=[f"{c['file_path']}::{c['function_name']}::{c['start_line']}" for c in batch],
            embeddings=[c["embedding"] for c in batch],
            documents=[c["code"] for c in batch],
            metadatas=[{
                "file_path": c["file_path"],
                "function_name": c["function_name"],
                "language": c["language"],
                "start_line": c["start_line"],
                "end_line": c["end_line"],
            } for c in batch],
        )
        print(f"  Stored {min(i + batch_size, len(valid))}/{len(valid)}")

    print(f"Done. ChromaDB at: {CHROMA_PERSIST_DIR}")
    return len(valid)


def query(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Query the collection. Returns [] if no collection exists yet."""
    client = get_client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        return []

    count = collection.count()
    if count == 0:
        return []

    # Don't request more results than what's stored
    n = min(top_k, count)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )
    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({"code": doc, "metadata": meta, "distance": dist})
    return chunks


def get_status() -> dict:
    """Return indexing status: how many chunks are stored."""
    client = get_client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
        # Sample a few to get languages + files
        if count > 0:
            sample = collection.get(limit=min(count, 500), include=["metadatas"])
            files  = {m["file_path"] for m in sample["metadatas"]}
            langs  = {m["language"]  for m in sample["metadatas"]}
        else:
            files, langs = set(), set()
        return {
            "indexed": True,
            "chunk_count": count,
            "file_count": len(files),
            "languages": sorted(langs),
            "persist_dir": CHROMA_PERSIST_DIR,
        }
    except Exception:
        return {
            "indexed": False,
            "chunk_count": 0,
            "file_count": 0,
            "languages": [],
            "persist_dir": CHROMA_PERSIST_DIR,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["store", "query", "clear", "status"], required=True)
    parser.add_argument("--input", default=_DEFAULT_INPUT)
    parser.add_argument("--query", default="")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    if args.action == "store":
        store(args.input)

    elif args.action == "query":
        # For CLI testing only — real queries go through rag_query.py
        from embed_chunks import embed_batch
        embedding = embed_batch([args.query])[0]
        results = query(embedding, args.top_k)
        if not results:
            print("No results — have you run --action store yet?")
            return
        for r in results:
            print(f"\n--- {r['metadata']['file_path']} L{r['metadata']['start_line']}-{r['metadata']['end_line']} (dist={r['distance']:.4f}) ---")
            print(r["code"][:300])

    elif args.action == "clear":
        client = get_client()
        try:
            client.delete_collection(COLLECTION_NAME)
            print("Collection cleared.")
        except Exception:
            print("No collection to clear.")

    elif args.action == "status":
        s = get_status()
        print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
