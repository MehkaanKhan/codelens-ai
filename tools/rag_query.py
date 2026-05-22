"""
Full RAG query chain: embed query → retrieve top-k chunks → build Gemma prompt → return answer.

Usage: python tools/rag_query.py --query "Where is the authentication logic?"
"""

import argparse
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "codelens-gemma")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "gemma3:4b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

SYSTEM_PROMPT = """You are a code assistant. Answer ONLY using the provided code context below.
If the answer is not in the context, say "I don't know based on the indexed codebase."
Always cite the source file and line range at the end of your answer, like: [Source: src/auth.py L42-67]"""


def embed_query(query: str) -> list[float]:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": [query]},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["embeddings"][0]


def generate(prompt: str, model: str = None) -> str:
    model = model or LLM_MODEL
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["response"]


def generate_stream(prompt: str, model: str = None):
    model = model or LLM_MODEL
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": True},
        timeout=120,
        stream=True,
    )
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            yield data.get("response", "")
            if data.get("done"):
                break


def run_rag_query(query: str, top_k: int = 5) -> dict:
    """
    Returns: { "answer": str, "sources": [{ "file_path", "start_line", "end_line", "snippet" }] }
    """
    from chroma_store import query as chroma_query

    query_embedding = embed_query(query)
    retrieved = chroma_query(query_embedding, top_k=top_k)

    if not retrieved:
        return {"answer": "No codebase indexed. Run /index first.", "sources": []}

    context_blocks = []
    sources = []
    for chunk in retrieved:
        meta = chunk["metadata"]
        context_blocks.append(
            f"[{meta['file_path']} L{meta['start_line']}-{meta['end_line']}]\n{chunk['code'][:1000]}"
        )
        sources.append({
            "file_path": meta["file_path"],
            "start_line": meta["start_line"],
            "end_line": meta["end_line"],
            "snippet": chunk["code"][:200],
        })

    context = "\n\n---\n\n".join(context_blocks)
    prompt = f"{SYSTEM_PROMPT}\n\nContext:\n{context}\n\nQuestion: {query}\n\nAnswer:"

    try:
        answer = generate(prompt, model=LLM_MODEL)
    except Exception:
        answer = generate(prompt, model=FALLBACK_LLM_MODEL)

    return {"answer": answer, "sources": sources}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    result = run_rag_query(args.query, args.top_k)
    print(f"\nAnswer:\n{result['answer']}")
    print(f"\nSources:")
    for s in result["sources"]:
        print(f"  {s['file_path']} L{s['start_line']}-{s['end_line']}")


if __name__ == "__main__":
    main()
