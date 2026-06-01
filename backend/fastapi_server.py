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
from typing import Optional

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434")
LLM_MODEL          = os.getenv("LLM_MODEL",          "codelens-qwen")
CONVERT_MODEL      = os.getenv("CONVERT_MODEL",      "qwen2.5-coder:3b")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "qwen2.5-coder:3b")
EMBED_MODEL        = os.getenv("EMBED_MODEL",         "nomic-embed-text")
BACKEND_HOST       = os.getenv("BACKEND_HOST",        "localhost")
BACKEND_PORT       = int(os.getenv("BACKEND_PORT",    "8080"))

# ── Path resolution ────────────────────────────────────────────────────────────
TOOLS_DIR = Path(__file__).parent.resolve()
REPO_ROOT  = TOOLS_DIR.parent.resolve()
TMP_DIR    = REPO_ROOT / ".tmp"

sys.path.insert(0, str(TOOLS_DIR))

app = FastAPI(title="CodeLens AI Backend", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_webapp_dir = REPO_ROOT / "webapp"
if _webapp_dir.exists():
    app.mount("/app", StaticFiles(directory=str(_webapp_dir), html=True), name="webapp")


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    repo_path: str

class ChatRequest(BaseModel):
    query: str
    top_k: int = 5

class ConvertRequest(BaseModel):
    code: str
    source_lang: str
    target_lang: str

class ConvertCodebaseRequest(BaseModel):
    repo_path:   str
    target_lang: str
    source_lang: Optional[str] = None   # None = auto-detect

class SummarizeRequest(BaseModel):
    repo_path: str

class DbQueryRequest(BaseModel):
    mode: str = "semantic"                 # "filter" | "semantic" | "both"
    query_text: Optional[str] = None       # required for "semantic" and "both"
    where: Optional[dict] = None           # ChromaDB metadata filter
    where_document: Optional[dict] = None  # ChromaDB document text filter
    top_k: int = 10                        # n_results for semantic/both
    limit: int = 20                        # limit for filter mode


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run(script: str, extra_args: list[str] | None = None) -> None:
    cmd    = [sys.executable, str(TOOLS_DIR / script)] + (extra_args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"{script} exited {result.returncode}")


# ─────────────────────────────────────────────────────────────────────────────
# Health / Status
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        resp   = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return {
            "status": "ok",
            "ollama": "running",
            "models_available": models,
            "llm_ready":   any(LLM_MODEL in m or FALLBACK_LLM_MODEL in m for m in models),
            "embed_ready": any(EMBED_MODEL in m for m in models),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama not reachable: {e}")


@app.get("/rag-status")
def rag_status():
    from chroma_store import get_status
    return get_status()


# ─────────────────────────────────────────────────────────────────────────────
# Index / Graph
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/index")
def index_repo(req: IndexRequest):
    repo = Path(req.repo_path).resolve()
    if not repo.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.repo_path}")

    try:    _run("parse_codebase.py", ["--repo-path", str(repo)])
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {e}")

    try:    _run("embed_chunks.py")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Embed failed: {e}")

    try:    _run("chroma_store.py", ["--action", "store"])
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Store failed: {e}")

    try:    _run("build_graph.py", ["--repo-path", str(repo)])
    except RuntimeError as e:
        print(f"[WARN] Graph build failed (non-fatal): {e}")

    from chroma_store import get_status
    s = get_status()
    return {"status": "indexed", "repo_path": str(repo), **s}


@app.get("/graph")
def get_graph():
    graph_path = TMP_DIR / "graph.json"
    if not graph_path.exists():
        raise HTTPException(status_code=404, detail="No graph found. Run /index first.")
    import json
    return json.loads(graph_path.read_text(encoding="utf-8"))


@app.get("/graph/node/{node_id:path}")
def get_node_details(node_id: str):
    graph_path = TMP_DIR / "graph.json"
    if not graph_path.exists():
        raise HTTPException(status_code=404, detail="No graph found.")
    import json
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    node  = next((n for n in graph["nodes"] if n["id"] == node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    outgoing = [l for l in graph["links"] if l["source"] == node_id]
    incoming = [l for l in graph["links"] if l["target"] == node_id]
    return {
        **node,
        "imports":         [l["target"] for l in outgoing],
        "imported_by":     [l["source"] for l in incoming],
        "import_count":    len(outgoing),
        "imported_by_count": len(incoming),
        "degree":          len(outgoing) + len(incoming),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chat / RAG
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/chat")
def chat(req: ChatRequest):
    from rag_query import run_rag_query
    try:
        return run_rag_query(req.query, top_k=req.top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    import json
    from rag_query import run_rag_query_stream
    def _gen():
        try:
            for event in run_rag_query_stream(req.query, top_k=req.top_k):
                yield json.dumps(event) + "\n"
        except Exception as e:
            yield json.dumps({"type": "token", "token": f"\n\n⚠️ Stream error: {e}"}) + "\n"
    return StreamingResponse(_gen(), media_type="text/plain")


@app.post("/summarize-repo")
def summarize_repo(req: SummarizeRequest):
    from rag_query import run_rag_query
    sections = [
        "What is the main purpose of this codebase?",
        "What are the key entry points and how does execution start?",
        "What are the major modules or components and what does each do?",
        "What are the most important files a new developer should read first?",
        "What external dependencies or services does this project rely on?",
    ]
    titles = ["Overview", "Entry Points", "Major Modules", "Recommended Reading Order", "Dependencies"]
    parts  = ["# Codebase Onboarding Guide\n\n*Generated by CodeLens AI*\n"]
    for title, question in zip(titles, sections):
        result = run_rag_query(question, top_k=5)
        parts.append(f"## {title}\n\n{result['answer']}\n")
    return {"markdown": "\n".join(parts)}


# ─────────────────────────────────────────────────────────────────────────────
# Single-file conversion  (existing)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/convert")
def convert_code(req: ConvertRequest):
    from codebase_converter import _lang_rules, _strip_fences
    lang_rules = _lang_rules(req.target_lang)
    prompt = (
        f"You are an expert programmer converting {req.source_lang} code "
        f"to idiomatic {req.target_lang}. Preserve all functionality and logic exactly.\n"
        f"{lang_rules}\n\n"
        f"Output ONLY the translated code with no explanation or markdown fences.\n\n"
        f"```{req.source_lang}\n{req.code}\n```\n\n"
        f"{req.target_lang} code:"
    )
    def _try(model: str) -> str:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "keep_alive": -1},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["response"]

    try:
        converted = _try(CONVERT_MODEL)
    except Exception:
        try:
            converted = _try(FALLBACK_LLM_MODEL)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    converted = _strip_fences(converted)
    return {"converted_code": converted, "source_lang": req.source_lang, "target_lang": req.target_lang}


# ─────────────────────────────────────────────────────────────────────────────
# Multi-file / codebase conversion  (NEW)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/convert/codebase")
def start_codebase_conversion(req: ConvertCodebaseRequest):
    """
    Start converting an entire local directory to target_lang.
    Returns { job_id } immediately — poll GET /convert/job/{job_id} for progress.
    """
    repo = Path(req.repo_path).resolve()
    if not repo.exists():
        raise HTTPException(400, detail=f"Path not found: {req.repo_path}")
    if not repo.is_dir():
        raise HTTPException(400, detail=f"Not a directory: {req.repo_path}")

    from codebase_converter import convert_codebase, make_zip, start_job

    def _job(on_progress):
        converted = convert_codebase(
            root=repo,
            target_lang=req.target_lang,
            source_lang=req.source_lang,
            on_progress=on_progress,
        )
        return make_zip(converted, root_folder=f"{repo.name}_{req.target_lang}")

    job_id = start_job(_job)
    return {"job_id": job_id, "repo_path": str(repo), "target_lang": req.target_lang}


@app.post("/convert/zip")
async def start_zip_conversion(
    file:        UploadFile = File(...),
    target_lang: str        = Form(...),
    source_lang: Optional[str] = Form(None),
):
    """
    Upload a .zip archive → translate all source files → return job_id.
    Download result with GET /convert/job/{job_id}/download.
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, detail="Only .zip files are accepted.")

    zip_bytes = await file.read()
    if len(zip_bytes) > 100 * 1024 * 1024:   # 100 MB guard
        raise HTTPException(413, detail="ZIP too large (max 100 MB).")

    from codebase_converter import convert_from_zip, start_job

    def _job(on_progress):
        return convert_from_zip(
            zip_bytes=zip_bytes,
            target_lang=target_lang,
            source_lang=source_lang or None,
            on_progress=on_progress,
        )

    job_id = start_job(_job)
    return {"job_id": job_id, "filename": file.filename, "target_lang": target_lang}


@app.get("/convert/job/{job_id}")
def get_conversion_job(job_id: str):
    """Poll conversion progress."""
    from codebase_converter import get_job
    j = get_job(job_id)
    if j is None:
        raise HTTPException(404, detail="Job not found.")

    # Return last 40 log entries so the UI stays responsive
    recent_log = j["log"][-40:]
    pct = round(100 * j["done"] / j["total"]) if j["total"] else 0

    return {
        "job_id":     job_id,
        "status":     j["status"],          # "running" | "done" | "error"
        "total":      j["total"],
        "done":       j["done"],
        "percent":    pct,
        "log":        recent_log,           # list of {path, status}
        "has_result": j["zip"] is not None,
        "error":      j["error"],
    }


@app.get("/convert/job/{job_id}/download")
def download_conversion_result(job_id: str):
    """Download the converted ZIP archive."""
    from codebase_converter import get_job
    j = get_job(job_id)
    if j is None:
        raise HTTPException(404, detail="Job not found.")
    if j["zip"] is None:
        raise HTTPException(400, detail="Job not complete yet." if j["status"] == "running"
                                         else f"Job failed: {j['error']}")
    return Response(
        content=j["zip"],
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="codelens_converted_{job_id}.zip"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Database Showcase
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/db/overview")
def db_overview():
    import chromadb
    from chroma_store import get_status, CHROMA_PERSIST_DIR, COLLECTION_NAME
    status = get_status()
    try:
        version = chromadb.__version__
    except Exception:
        version = "unknown"
    return {
        "collection_name": COLLECTION_NAME,
        "hnsw_space": "cosine",
        "chromadb_version": version,
        **status,
    }


@app.get("/db/facets")
def db_facets():
    from chroma_store import get_client, COLLECTION_NAME
    client = get_client()
    try:
        col = client.get_collection(COLLECTION_NAME)
        count = col.count()
        if count == 0:
            return {"languages": [], "files": []}
        sample = col.get(limit=min(count, 5000), include=["metadatas"])
        langs  = sorted({m["language"]  for m in sample["metadatas"]})
        files  = sorted({m["file_path"] for m in sample["metadatas"]})
        return {"languages": langs, "files": files}
    except Exception:
        return {"languages": [], "files": []}


@app.get("/db/browse")
def db_browse(
    offset: int = 0,
    limit: int = 20,
    language: str = "",
    file_contains: str = "",
):
    from chroma_store import get_client, COLLECTION_NAME
    client = get_client()
    try:
        col   = client.get_collection(COLLECTION_NAME)
        total = col.count()
        if total == 0:
            return {"total": 0, "total_unfiltered": 0, "offset": 0, "limit": limit, "items": []}

        where      = {"language": language} if language else None
        fetch_cap  = min(total, 5000)
        kwargs     = {"limit": fetch_cap, "include": ["documents", "metadatas"]}
        if where:
            kwargs["where"] = where
        result = col.get(**kwargs)

        rows = list(zip(result["ids"], result["documents"], result["metadatas"]))

        if file_contains:
            needle = file_contains.lower()
            rows   = [(i, d, m) for i, d, m in rows if needle in m["file_path"].lower()]

        total_filtered = len(rows)
        page           = rows[offset : offset + limit]

        items = [
            {
                "id":            chunk_id,
                "file_path":     meta["file_path"],
                "function_name": meta["function_name"],
                "language":      meta["language"],
                "start_line":    meta["start_line"],
                "end_line":      meta["end_line"],
                "code_preview":  doc[:200],
                "code_full":     doc,
            }
            for chunk_id, doc, meta in page
        ]
        return {
            "total":            total_filtered,
            "total_unfiltered": total,
            "offset":           offset,
            "limit":            limit,
            "items":            items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/db/query")
def db_query(req: DbQueryRequest):
    import json as _json
    from chroma_store import get_client, COLLECTION_NAME

    client = get_client()
    try:
        col   = client.get_collection(COLLECTION_NAME)
        count = col.count()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if count == 0:
        return {"mode": req.mode, "results": [], "total": 0, "executed_query": "# collection is empty"}

    def _build_item(doc, meta, dist=None):
        item = {
            "file_path":     meta["file_path"],
            "function_name": meta["function_name"],
            "language":      meta["language"],
            "start_line":    meta["start_line"],
            "end_line":      meta["end_line"],
            "code":          doc,
            "distance":      round(dist, 4) if dist is not None else None,
            "similarity_pct": round((1 - dist) * 100, 1) if dist is not None else None,
        }
        return item

    # ── filter mode: collection.get() ──────────────────────────────────────────
    if req.mode == "filter":
        kwargs: dict = {"include": ["documents", "metadatas"], "limit": max(1, req.limit)}
        if req.where:         kwargs["where"]          = req.where
        if req.where_document: kwargs["where_document"] = req.where_document
        try:
            result = col.get(**kwargs)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"ChromaDB error: {e}")

        items = [_build_item(d, m) for d, m in zip(result["documents"], result["metadatas"])]

        lines = ["collection.get("]
        if req.where:          lines.append(f"    where={_json.dumps(req.where)},")
        if req.where_document: lines.append(f"    where_document={_json.dumps(req.where_document)},")
        lines += [f"    limit={req.limit},", '    include=["documents", "metadatas"]', ")"]
        return {"mode": req.mode, "results": items, "total": len(items), "executed_query": "\n".join(lines)}

    # ── semantic / both modes: collection.query() ───────────────────────────────
    if not req.query_text:
        raise HTTPException(status_code=400, detail="query_text is required for semantic and both modes")

    from embed_chunks import embed_batch
    try:
        embedding = embed_batch([req.query_text])[0]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Embedding failed — is Ollama running? {e}")

    n = min(req.top_k, count)
    kwargs = {
        "query_embeddings": [embedding],
        "n_results":        n,
        "include":          ["documents", "metadatas", "distances"],
    }
    if req.where:          kwargs["where"]          = req.where
    if req.where_document: kwargs["where_document"] = req.where_document

    try:
        results = col.query(**kwargs)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ChromaDB error: {e}")

    items = [
        _build_item(d, m, dist)
        for d, m, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]

    q_escaped = req.query_text.replace('"', '\\"')
    lines = [f'collection.query(', f'    query_embeddings=[embed("{q_escaped}")],']
    if req.where:          lines.append(f"    where={_json.dumps(req.where)},")
    if req.where_document: lines.append(f"    where_document={_json.dumps(req.where_document)},")
    lines += [f"    n_results={n},", '    include=["documents", "metadatas", "distances"]', ")"]
    return {"mode": req.mode, "query": req.query_text, "top_k": n, "results": items,
            "total": len(items), "executed_query": "\n".join(lines)}


# ─────────────────────────────────────────────────────────────────────────────
# BLEU evaluation results
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/bleu-results")
def bleu_results():
    """Return Phase 7 BLEU evaluation results (from finetune/bleu_results.json)."""
    import json as _json
    results_path = REPO_ROOT / "finetune" / "bleu_results.json"
    if not results_path.exists():
        raise HTTPException(status_code=404, detail="BLEU results not yet available. Run finetune/bleu_eval.py first.")
    return _json.loads(results_path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT, reload=False)
