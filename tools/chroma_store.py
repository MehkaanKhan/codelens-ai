"""
Store and retrieve code chunk embeddings in ChromaDB.

Usage:
  python tools/chroma_store.py --action store [--input .tmp/chunks_with_embeddings.jsonl]
  python tools/chroma_store.py --action query --query "authentication logic" --top-k 5
  python tools/chroma_store.py --action clear
"""

import argparse
import json
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv

load_dotenv()

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", ".tmp/chromadb")
COLLECTION_NAME = "codelens_chunks"


def get_client():
    return chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def store(input_path: str):
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


def query(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    client = get_client()
    collection = client.get_collection(COLLECTION_NAME)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["store", "query", "clear"], required=True)
    parser.add_argument("--input", default=".tmp/chunks_with_embeddings.jsonl")
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
        for r in results:
            print(f"\n--- {r['metadata']['file_path']} L{r['metadata']['start_line']}-{r['metadata']['end_line']} (dist={r['distance']:.4f}) ---")
            print(r["code"][:300])

    elif args.action == "clear":
        client = get_client()
        client.delete_collection(COLLECTION_NAME)
        print("Collection cleared.")


if __name__ == "__main__":
    main()
