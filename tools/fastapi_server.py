"""
FastAPI backend for CodeLens AI.
Exposes endpoints consumed by the VS Code extension.

Run: python tools/fastapi_server.py
Default: http://localhost:8080
"""

import os
import subprocess
import sys
from pathlib import Path

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "codelens-gemma")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "gemma3:4b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
BACKEND_HOST = os.getenv("BACKEND_HOST", "localhost")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8080"))

# Add tools/ to path so we can import sibling scripts
sys.path.insert(0, str(Path(__file__).parent))

app = FastAPI(title="CodeLens AI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Models ---

class IndexRequest(BaseModel):
    repo_path: str

class ChatRequest(BaseModel):
    query: str
    top_k: int = 5

class ConvertRequest(BaseModel):
    code: str
    source_lang: str
    target_lang: str

class SummarizeRequest(BaseModel):
    repo_path: str


# --- Endpoints ---

@app.get("/health")
def health():
    """Check Ollama connectivity and model availability."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return {
            "status": "ok",
            "ollama": "running",
            "models_available": models,
            "llm_ready": any(LLM_MODEL in m or FALLBACK_LLM_MODEL in m for m in models),
            "embed_ready": any(EMBED_MODEL in m for m in models),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama not reachable: {e}")


@app.post("/index")
def index_repo(req: IndexRequest):
    """Parse, embed, and store a repository in ChromaDB."""
    repo = Path(req.repo_path)
    if not repo.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.repo_path}")

    tools_dir = Path(__file__).parent

    # Step 1: Parse
    result = subprocess.run(
        [sys.executable, str(tools_dir / "parse_codebase.py"), "--repo-path", str(repo)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Parse failed: {result.stderr}")

    # Step 2: Embed
    result = subprocess.run(
        [sys.executable, str(tools_dir / "embed_chunks.py")],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Embed failed: {result.stderr}")

    # Step 3: Store
    result = subprocess.run(
        [sys.executable, str(tools_dir / "chroma_store.py"), "--action", "store"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Store failed: {result.stderr}")

    # Step 4: Dependency graph
    result = subprocess.run(
        [sys.executable, str(tools_dir / "build_graph.py"), "--repo-path", str(repo)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Graph build failed: {result.stderr}")

    return {"status": "indexed", "repo_path": str(repo)}


@app.post("/chat")
def chat(req: ChatRequest):
    """RAG-powered Q&A grounded in the indexed codebase."""
    from rag_query import run_rag_query
    try:
        result = run_rag_query(req.query, top_k=req.top_k)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/convert")
def convert_code(req: ConvertRequest):
    """Cross-language code conversion using the fine-tuned model."""
    prompt = (
        f"Convert the following {req.source_lang} code to idiomatic {req.target_lang}. "
        f"Preserve functionality, idioms, and structure. "
        f"Add inline comments explaining each translated block.\n\n"
        f"```{req.source_lang}\n{req.code}\n```\n\n"
        f"```{req.target_lang}"
    )
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
            timeout=180,
        )
        resp.raise_for_status()
        converted = resp.json()["response"]
        return {"converted_code": converted, "source_lang": req.source_lang, "target_lang": req.target_lang}
    except requests.HTTPError as e:
        # Fallback to base model if fine-tuned model not yet available
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": FALLBACK_LLM_MODEL, "prompt": prompt, "stream": False},
            timeout=180,
        )
        resp.raise_for_status()
        converted = resp.json()["response"]
        return {"converted_code": converted, "source_lang": req.source_lang, "target_lang": req.target_lang}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/summarize-repo")
def summarize_repo(req: SummarizeRequest):
    """Generate a structured onboarding guide for a repository."""
    from rag_query import run_rag_query

    sections = [
        "What is the main purpose of this codebase?",
        "What are the key entry points and how does execution start?",
        "What are the major modules or components and what does each do?",
        "What are the most important files a new developer should read first?",
        "What external dependencies or services does this project rely on?",
    ]

    guide_parts = ["# Codebase Onboarding Guide\n\n*Generated by CodeLens AI*\n"]
    section_titles = ["Overview", "Entry Points", "Major Modules", "Recommended Reading Order", "Dependencies"]

    for title, question in zip(section_titles, sections):
        result = run_rag_query(question, top_k=5)
        guide_parts.append(f"## {title}\n\n{result['answer']}\n")

    return {"markdown": "\n".join(guide_parts)}


@app.get("/graph")
def get_graph():
    """Return the dependency graph JSON for the currently indexed repo."""
    graph_path = Path(".tmp/graph.json")
    if not graph_path.exists():
        raise HTTPException(status_code=404, detail="No graph found. Run /index first.")
    import json
    return json.loads(graph_path.read_text())


if __name__ == "__main__":
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT, reload=False)
