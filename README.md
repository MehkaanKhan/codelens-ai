<div align="center">

# CodeLens AI

**AI-powered codebase intelligence for VS Code — fully offline, no cloud APIs.**

Index, explain, visualize, and translate entire codebases from inside your editor,
powered by a locally hosted, fine-tuned LLM. Not a single line of code ever leaves your machine.

</div>

---

## What it does

| | Feature | Description |
|---|---|---|
| 💬 | **Codebase Q&A (RAG)** | Ask natural-language questions about any indexed repo and get answers grounded in the real source, with clickable file/line citations. |
| 🕸️ | **Dependency Graph** | An interactive, navigable map of how files and classes depend on one another. |
| 🔄 | **Whole-Codebase Translation** | A multi-pass, schema-driven pipeline that converts an entire multi-file project between languages while preserving cross-file consistency, inheritance, and persistence logic. |

The defining constraint: **everything runs 100% locally** through Ollama — usable in privacy-sensitive, air-gapped, or proprietary-code environments where cloud AI tools are forbidden.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│              VS Code Extension  (Frontend, TS)            │
│   @codelens-ai chat · ChatPanel · ConverterPanel · Graph  │
└───────────────────────────┬──────────────────────────────┘
                            │  HTTP · localhost:8080 · REST/JSON
┌───────────────────────────▼──────────────────────────────┐
│                 FastAPI Backend  (Python)                 │
│   RAG pipeline · dependency graph · converter pipeline    │
└──────────────┬──────────────────────────┬─────────────────┘
               │                          │
        ┌──────▼───────┐          ┌────────▼─────────┐
        │   ChromaDB   │          │      Ollama       │
        │ + nomic-embed│          │ codelens-qwen     │
        │ (vectors)    │          │ qwen2.5-coder:7b  │
        └──────────────┘          └───────────────────┘
```

---

## Repository structure

The repo is organized to map directly onto the four project pillars:

| Pillar | Folder | Contents |
|---|---|---|
| **Frontend Code** | [`src/`](src/) | TypeScript VS Code extension — chat participant, webview panels, server lifecycle |
| **Backend Code** | [`backend/`](backend/) | FastAPI server, RAG pipeline, dependency-graph builder, converter pipeline |
| **Model / AI Code** | [`model/`](model/) | QLoRA fine-tuning notebook, training scripts, Modelfile, GGUF model, BLEU evaluation |
| **Dataset & Training** | [`dataset/`](dataset/) | Dataset download / formatting / mixing scripts and processed splits |

> 📖 **Full system design, pipeline internals, and benchmarks:** [`PROJECT_DOCUMENTATION.md`](PROJECT_DOCUMENTATION.md)

---

## Models

| Role | Model | Notes |
|---|---|---|
| Chat / RAG | `codelens-qwen` | Qwen2.5-Coder **3B**, fine-tuned with QLoRA, exported to GGUF, served via Ollama |
| Conversion | `qwen2.5-coder:7b` | Larger model for cross-file consistency; fits in 4-bit (~4–5 GB VRAM) on an RTX 4060 |
| Embeddings | `nomic-embed-text` | Powers semantic retrieval into ChromaDB |

**Fine-tuning results** (50-sample held-out set):

| Model | BLEU | Token-F1 |
|---|---|---|
| Base `qwen2.5-coder:3b` | 11.49 | 0.155 |
| **Fine-tuned `codelens-qwen`** | **65.06** | **0.617** |
| **Improvement** | **+53.56** (~5.7×) | **+0.462** |

---

## Getting started

### Prerequisites

- **Python** 3.10+
- **Node.js** (for the extension build)
- **[Ollama](https://ollama.com)** — with the models registered (`codelens-qwen`, `qwen2.5-coder:7b`, `nomic-embed-text`)

### Install

```bash
pip install -r requirements.txt
npm install
```

### Run

```bash
# Start the backend (the extension also launches this automatically)
python -X utf8 backend/fastapi_server.py     # serves on http://localhost:8080
```

Then open the project in VS Code and press **F5** to launch the Extension Development Host.

### Use

| Command | Action |
|---|---|
| `CodeLens AI: Index Current Workspace` | Build the RAG index for your repo |
| `@codelens-ai` (in chat) | Ask questions about your codebase |
| `CodeLens AI: Open Code Converter` | Translate a whole project to another language |
| `CodeLens AI: Open Dependency Graph` | Explore project architecture visually |

### Configuration

| Setting | Default | Description |
|---|---|---|
| `codelens-ai.pythonPath` | `python` | Python interpreter used to run the backend |
| `codelens-ai.backendPort` | `8080` | Port the FastAPI backend listens on |

---

## Tech stack

**Frontend:** TypeScript · VS Code Extension API · webpack
**Backend:** Python · FastAPI · Uvicorn · Pydantic
**AI/ML:** Ollama · Qwen2.5-Coder (3B fine-tuned + 7B) · QLoRA · ChromaDB · Tree-sitter
**Quality tooling:** black · prettier · clang-format · pyflakes · tsc · javac · g++

---

## Design principles

1. **Offline by mandate** — no code ever leaves the machine; no external API is ever called.
2. **Deterministic-first** — compute everything computable; fence the LLM inside a hard contract.
3. **Whole-project reasoning** — schema + dependency graph + per-class callable contracts before generation.
4. **Ground truth before generation** — never let an LLM-generated "fact" precede real source in a prompt.
5. **Build specific checkers, not bigger verifiers** — semantic bugs invisible to compilers get purpose-built detectors.
6. **Fail soft** — stub injection and bounded repair loops keep output runnable even when a stage falls short.

---

<div align="center">

Built as a fully local alternative to cloud AI coding assistants.
See [`PROJECT_DOCUMENTATION.md`](PROJECT_DOCUMENTATION.md) for the complete technical deep-dive.

</div>
