# Phase 4: RAG Pipeline + FastAPI Backend

**Timeline:** Days 12–18  
**Owner:** Abdullah Raza  
**Goal:** A retrieval layer that grounds model answers in actual codebase content, served via FastAPI.

## Required Inputs
- Ollama running with `codelens-gemma` and `nomic-embed-text` models
- Target codebase directory path (passed at runtime)
- `.env` with `OLLAMA_BASE_URL`, `CHROMA_PERSIST_DIR`, `BACKEND_PORT`

## Tools
- `tools/parse_codebase.py` — Tree-sitter AST chunking of source files
- `tools/embed_chunks.py` — sends chunks to nomic-embed-text, returns vectors
- `tools/chroma_store.py` — stores/retrieves vectors from ChromaDB
- `tools/rag_query.py` — full retrieval chain: embed query → top-k chunks → Gemma prompt
- `tools/fastapi_server.py` — FastAPI app exposing `/chat`, `/convert`, `/summarize-repo` endpoints

## Architecture

```
User query (VS Code)
    │
    ▼
FastAPI /chat endpoint
    │
    ▼
RAG Query Tool
    ├── embed query with nomic-embed-text (Ollama)
    ├── retrieve top-5 chunks from ChromaDB
    └── build prompt: [system] + [retrieved chunks] + [user question]
    │
    ▼
Gemma 3 (Ollama) → grounded answer with source citations
    │
    ▼
Response to VS Code extension
```

## Steps

### 4.1 Parse Code with Tree-sitter
Split files into function/class-level chunks — NOT line-based splitting.
```bash
python tools/parse_codebase.py --repo-path /path/to/target/repo
```
Supported languages: Python, JS, TS, Java, C, C++, Rust, Go.
Output: `.tmp/chunks.jsonl` with fields: `file_path`, `function_name`, `language`, `start_line`, `end_line`, `code`

### 4.2 Embed with nomic-embed-text
```bash
python tools/embed_chunks.py
```
Calls Ollama's embed endpoint (`/api/embed`) for each chunk.
Output: `.tmp/chunks_with_embeddings.jsonl`

### 4.3 Store in ChromaDB
```bash
python tools/chroma_store.py --action store
```
Creates a local ChromaDB collection at `.tmp/chromadb/`.
Metadata per chunk: `file_path`, `function_name`, `language`, `start_line`, `end_line`

### 4.4 RAG Query Chain
System prompt constraint (critical — prevents hallucination):
```
You are a code assistant. Answer ONLY using the provided code context.
If the answer is not in the context, say "I don't know based on the indexed codebase."
Always cite the source file and line range for your answer.
```
Retrieval: top-5 chunks by cosine similarity.

### 4.5 FastAPI Backend Endpoints
Run: `python tools/fastapi_server.py`
Default: `http://localhost:8080`

**POST `/index`** — parse, embed, and store a repo
```json
{ "repo_path": "/absolute/path/to/repo" }
```

**POST `/chat`** — RAG-powered Q&A
```json
{ "query": "Where is the authentication logic?" }
```
Response includes `answer` and `sources` (file + line range).

**POST `/convert`** — code conversion
```json
{ "code": "...", "source_lang": "python", "target_lang": "rust" }
```

**POST `/summarize-repo`** — generate onboarding guide
```json
{ "repo_path": "/path/to/repo" }
```
Returns structured Markdown.

**GET `/health`** — check Ollama connectivity and model availability.

## Expected Outputs
- [ ] `tools/fastapi_server.py` running on port 8080
- [ ] `/health` returns 200 with both models confirmed
- [ ] `/index` successfully chunks and embeds a test repo
- [ ] `/chat` returns grounded answers with source citations
- [ ] `/convert` returns translated code with inline comments

## Edge Cases
- **Tree-sitter language bindings:** Must install per-language: `pip install tree-sitter-python tree-sitter-javascript` etc.
- **ChromaDB collection exists:** On re-index, delete old collection first or use `--overwrite` flag.
- **Ollama not running:** `/health` must return a clear error message; extension shows "Start Ollama first" toast.
- **Large repos (10K+ files):** Embed in batches of 100 to avoid memory spikes. Add `--batch-size` flag to `embed_chunks.py`.
- **Embedding model latency:** nomic-embed-text is fast but CPU-bound. First indexing of a large repo may take 5–10 min — show progress in sidebar.
