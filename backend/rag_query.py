"""
Full RAG query chain: embed query → retrieve top-k chunks → build Gemma prompt → return answer.

Usage: python tools/rag_query.py --query "Where is the authentication logic?"
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Ensure tools/ is on path so sibling modules import cleanly ────────────────
sys.path.insert(0, str(Path(__file__).parent))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "codelens-gemma")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "gemma3:4b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

SYSTEM_PROMPT = (
    "You are CodeLens AI — a senior developer assistant that understands codebases deeply. "
    "Answer the developer's question using the provided code context. "
    "Be specific: reference function names, file paths, and line numbers. "
    "If the answer spans multiple files, explain how they connect. "
    "If the context does not contain the answer, say so clearly and suggest what to look for. "
    "Always cite sources at the end like: [Source: src/auth.py L42-67]"
)


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
        json={"model": model, "prompt": prompt, "stream": False, "keep_alive": -1},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["response"]


def generate_stream(prompt: str, model: str = None):
    model = model or LLM_MODEL
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": True, "keep_alive": -1},
        timeout=180,
        stream=True,
    )
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            yield data.get("response", "")
            if data.get("done"):
                break


def run_rag_query_stream(query: str, top_k: int = 5):
    """
    Generator yielding newline-delimited JSON events:
      {"type":"sources","sources":[...]}
      {"type":"token","token":"..."}  (one per LLM token)
    """
    from chroma_store import query as chroma_query, get_status

    status = get_status()
    if not status["indexed"] or status["chunk_count"] == 0:
        yield {"type": "token", "token": (
            "⚠️ **Codebase not indexed yet.**\n\n"
            "Run **CodeLens AI: Index Workspace** (Ctrl+Shift+P) first."
        )}
        return

    yield {"type": "status", "message": "🔍 Searching codebase..."}

    try:
        query_embedding = embed_query(query)
    except Exception as e:
        yield {"type": "token", "token": f"⚠️ Could not embed query. Is Ollama running?\n\nError: {e}"}
        return

    retrieved = chroma_query(query_embedding, top_k=top_k)

    if not retrieved:
        yield {"type": "token", "token": (
            "No relevant code found.\n\n"
            "Try re-indexing or rephrase using function/file names from your code."
        )}
        return

    context_blocks = []
    sources = []
    for chunk in retrieved:
        meta = chunk["metadata"]
        fn_label = f" [{meta.get('function_name', '')}]" if meta.get("function_name") else ""
        context_blocks.append(
            f"[{meta['file_path']}{fn_label} L{meta['start_line']}-{meta['end_line']}]\n"
            f"{chunk['code'][:1200]}"
        )
        sources.append({
            "file_path": meta["file_path"],
            "start_line": meta["start_line"],
            "end_line": meta["end_line"],
            "snippet": chunk["code"][:200],
        })

    yield {"type": "sources", "sources": sources}
    yield {"type": "status", "message": "⚡ Generating response..."}

    context = "\n\n---\n\n".join(context_blocks)
    prompt = (
        f"[SYSTEM]: {SYSTEM_PROMPT}\n\n"
        f"### Indexed codebase context ({len(retrieved)} chunks retrieved):\n\n"
        f"{context}\n\n"
        f"### Developer question:\n{query}\n\n"
        f"### Answer:"
    )

    try:
        for token in generate_stream(prompt, model=LLM_MODEL):
            yield {"type": "token", "token": token}
    except Exception:
        try:
            for token in generate_stream(prompt, model=FALLBACK_LLM_MODEL):
                yield {"type": "token", "token": token}
        except Exception as e:
            yield {"type": "token", "token": f"\n\n⚠️ LLM error: {e}"}


def run_rag_query(query: str, top_k: int = 5) -> dict:
    """
    Returns: { "answer": str, "sources": [{ "file_path", "start_line", "end_line", "snippet" }] }
    """
    from chroma_store import query as chroma_query, get_status

    # ── Check that codebase has been indexed ───────────────────────────────────
    status = get_status()
    if not status["indexed"] or status["chunk_count"] == 0:
        return {
            "answer": (
                "⚠️ **Codebase not indexed yet.**\n\n"
                "Run **CodeLens AI: Index Workspace** (Ctrl+Shift+P) to index the open repo first.\n"
                "The RAG system needs to parse and embed your code before it can answer questions.\n\n"
                f"ChromaDB location: `{status['persist_dir']}`"
            ),
            "sources": [],
        }

    # ── Embed the query ────────────────────────────────────────────────────────
    try:
        query_embedding = embed_query(query)
    except Exception as e:
        return {
            "answer": f"⚠️ Could not embed query. Is Ollama running with `{EMBED_MODEL}`?\n\nError: {e}",
            "sources": [],
        }

    # ── Retrieve relevant chunks ───────────────────────────────────────────────
    retrieved = chroma_query(query_embedding, top_k=top_k)

    if not retrieved:
        return {
            "answer": (
                "No relevant code found for your query.\n\n"
                "Try re-indexing (**CodeLens AI: Index Workspace**) or rephrase your question "
                "using function names, file names, or keywords from your code."
            ),
            "sources": [],
        }

    # ── Build context & prompt ────────────────────────────────────────────────
    context_blocks = []
    sources = []
    for chunk in retrieved:
        meta = chunk["metadata"]
        # Show function name in context for better grounding
        fn_label = f" [{meta.get('function_name', '')}]" if meta.get('function_name') else ""
        context_blocks.append(
            f"[{meta['file_path']}{fn_label} L{meta['start_line']}-{meta['end_line']}]\n"
            f"{chunk['code'][:1200]}"
        )
        sources.append({
            "file_path": meta["file_path"],
            "start_line": meta["start_line"],
            "end_line": meta["end_line"],
            "snippet": chunk["code"][:200],
        })

    context = "\n\n---\n\n".join(context_blocks)
    prompt = (
        f"[SYSTEM]: {SYSTEM_PROMPT}\n\n"
        f"### Indexed codebase context ({len(retrieved)} chunks retrieved):\n\n"
        f"{context}\n\n"
        f"### Developer question:\n{query}\n\n"
        f"### Answer:"
    )

    # ── Generate answer with fallback ─────────────────────────────────────────
    try:
        answer = generate(prompt, model=LLM_MODEL)
    except Exception as primary_err:
        try:
            answer = generate(prompt, model=FALLBACK_LLM_MODEL)
        except Exception as fallback_err:
            answer = (
                f"⚠️ Could not generate answer. LLM error:\n"
                f"- Primary ({LLM_MODEL}): {primary_err}\n"
                f"- Fallback ({FALLBACK_LLM_MODEL}): {fallback_err}\n\n"
                f"Make sure Ollama is running: `ollama serve`"
            )

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
