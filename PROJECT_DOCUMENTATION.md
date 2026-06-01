# CodeLens AI — System Design & Project Documentation

> **AI-powered codebase intelligence for VS Code — fully offline, no cloud APIs.**
> A local LLM assistant that indexes, explains, visualizes, and translates entire codebases from inside the editor.

---

## 1. Abstract

**CodeLens AI** is a Visual Studio Code extension that brings large-language-model–powered code understanding to developers **without sending a single line of code to the cloud**. Everything — embeddings, retrieval, chat, and code conversion — runs on the developer's own machine through a locally hosted, fine-tuned Qwen2.5-Coder model served by Ollama.

The system delivers three core capabilities:

1. **Codebase Q&A (RAG)** — Ask natural-language questions about any indexed repository and get answers grounded in the actual source, with clickable file/line citations.
2. **Dependency Graph Visualization** — An interactive, navigable map of how files and classes depend on one another.
3. **Whole-Codebase Translation** — A multi-pass, schema-driven pipeline that converts an entire multi-file project from one language to another (e.g. C++ → Python, Java → C++) while preserving cross-file consistency, inheritance, and persistence logic.

The project's defining constraint — and its main contribution — is that it achieves this **100% offline**, making it usable in privacy-sensitive, air-gapped, or proprietary-code environments where cloud AI tools are forbidden.

---

## 2. Problem Statement & Motivation

Modern AI coding assistants (Copilot, Cursor, cloud Claude/GPT) share two structural problems:

| Problem | Consequence |
|---|---|
| **Code leaves the machine** | Proprietary / regulated / air-gapped codebases legally cannot use them. |
| **They reason file-by-file** | They lack a whole-project model, so multi-file refactors and translations break cross-file contracts (wrong method names, missing headers, circular imports). |

CodeLens AI targets both:

- **Privacy:** No external API is ever called. The hard architectural constraint is *"all AI runs through Ollama on the local machine."*
- **Whole-project reasoning:** The converter does not treat a project as a bag of files. It builds a **project schema**, a **deterministic dependency graph**, and a **per-class callable-method contract** before generating a single line, so translations stay internally consistent across dozens of files.

---

## 3. Objectives

1. Run a capable coding LLM entirely locally on consumer hardware (RTX 4060, 8 GB VRAM).
2. Provide grounded, cited answers about an indexed codebase (RAG), not hallucinated guesses.
3. Translate complete multi-file codebases between languages while preserving structure and semantics.
4. Visualize project architecture as an interactive dependency graph.
5. Deliver all of this through a native, polished VS Code experience.

---

## 4. System Architecture (High Level)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         VS Code Extension Host                        │
│                          (Frontend — TypeScript)                      │
│                                                                       │
│  @codelens-ai chat participant   ChatPanel   ConverterPanel   Graph   │
│           │                          │             │            │     │
└───────────┼──────────────────────────┼─────────────┼────────────┼─────┘
            │            HTTP (localhost:8080, REST + JSON)         │
┌───────────▼──────────────────────────▼─────────────▼────────────▼─────┐
│                      FastAPI Backend (Python)                         │
│                                                                       │
│   /chat   /index   /graph   /convert/codebase   /convert/job/{id}     │
│     │        │        │              │                                │
│  ┌──▼────────▼────┐ ┌─▼──────┐ ┌─────▼─────────────────────────────┐  │
│  │  RAG Pipeline  │ │ Graph  │ │   Codebase Converter Pipeline     │  │
│  │ parse→embed→   │ │ build  │ │  (schema → deterministic contract │  │
│  │ chroma→query   │ │_graph  │ │   → per-file LLM passes → repair) │  │
│  └───────┬────────┘ └────────┘ └─────────────────┬─────────────────┘  │
└──────────┼─────────────────────────────────────── ┼───────────────────┘
           │                                         │
   ┌───────▼─────────┐                      ┌────────▼─────────┐
   │  ChromaDB        │                     │     Ollama        │
   │ + nomic-embed    │                     │ codelens-qwen     │
   │   (vector store) │                     │ qwen2.5-coder:7b  │
   └──────────────────┘                     └───────────────────┘
```

The four submission categories map directly onto the repository:

| Category | Folder | What lives there |
|---|---|---|
| **Frontend Code** | [`src/`](src/) | TypeScript VS Code extension (chat participant, webview panels, server lifecycle) |
| **Backend Code** | [`backend/`](backend/) | FastAPI server, RAG pipeline, dependency-graph builder, converter pipeline |
| **Model / AI Code** | [`model/`](model/) | Fine-tuning notebook, training scripts, Modelfile, GGUF model, BLEU evaluation |
| **Dataset & Training Files** | [`dataset/`](dataset/) | Dataset download / formatting / mixing scripts and processed splits |

---

## 5. Frontend — VS Code Extension (`src/`)

Written in **TypeScript**, bundled with **webpack**. The extension is the user's entire surface area; it owns the backend lifecycle and renders all UI.

### 5.1 Responsibilities

- **Backend lifecycle** — On activation it spawns the FastAPI server (`backend/fastapi_server.py`) as a child process, polls `/health` until ready, and surfaces status in the VS Code **status bar** (`Starting → Ready / Not responding`). On deactivate it kills the process. *(See [extension.ts:30-70](src/extension.ts#L30-L70).)*
- **Native Chat Participant** — Registers `@codelens-ai` in VS Code's native chat. Questions are POSTed to `/chat`; answers stream back with **clickable source citations** rendered as `vscode.Location` anchors (file + line range). Includes suggested follow-ups (Entry points, Dependencies, Architecture). *(See [extension.ts:105-180](src/extension.ts#L105-L180).)*
- **Webview Panels** (`src/panels/`):
  - **ChatPanel** — Rich standalone chat UI.
  - **ConverterPanel** — Upload/select a codebase, pick target language, watch live job progress, download the converted ZIP.
  - **GraphPanel** — Interactive dependency-graph visualization.
- **Commands** (Command Palette):
  - `CodeLens AI: Open Chat`
  - `CodeLens AI: Open Code Converter`
  - `CodeLens AI: Open Dependency Graph`
  - `CodeLens AI: Index Current Workspace`
- **Configuration** — `codelens-ai.pythonPath` and `codelens-ai.backendPort` (default `8080`).

### 5.2 Notable design solutions

- **ZIP download from a webview** — Webviews can't trigger `<a download>` (security sandbox). Solution: the webview posts `{type:'openExternal', url}` and the extension host calls `vscode.env.openExternal()`.
- **Async progress** — Conversion is long-running, so the panel polls `GET /convert/job/{id}` every ~1.2 s and renders a progress bar rather than blocking.

---

## 6. Backend — FastAPI Server (`backend/`)

A single **FastAPI** application ([`fastapi_server.py`](backend/fastapi_server.py)) exposes the entire system over REST. All heavy logic lives in dedicated modules.

### 6.1 API surface

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness probe used by the extension on startup. |
| `GET /rag-status` | Whether a repo has been indexed and is queryable. |
| `POST /index` | Parse + chunk + embed a repository into ChromaDB. |
| `GET /graph` | Return the full dependency graph (nodes + edges). |
| `GET /graph/node/{id}` | Drill into a single node's neighbours. |
| `POST /chat` | RAG query → grounded answer + source citations. |
| `POST /chat/stream` | Streaming variant of `/chat`. |
| `POST /summarize-repo` | Whole-repository natural-language summary. |
| `POST /convert` | Convert a **single** code snippet/file. |
| `POST /convert/codebase` | Convert a **whole multi-file project** (async job). |
| `POST /convert/zip` | Convert an uploaded ZIP project (async job). |
| `GET /convert/job/{id}` | Poll async conversion progress. |
| `GET /convert/job/{id}/download` | Download the converted project ZIP. |
| `GET /bleu-results` | Serve the model's BLEU evaluation numbers. |

### 6.2 Backend modules

| Module | Role |
|---|---|
| [`parse_codebase.py`](backend/parse_codebase.py) | Tree-sitter AST parsing → function/class-level chunks. |
| [`embed_chunks.py`](backend/embed_chunks.py) | Embed chunks with `nomic-embed-text`. |
| [`chroma_store.py`](backend/chroma_store.py) | ChromaDB vector store read/write. |
| [`rag_query.py`](backend/rag_query.py) | Top-5 retrieval + prompt assembly + LLM answer. |
| [`build_graph.py`](backend/build_graph.py) | Construct the dependency graph from parsed imports. |
| [`codebase_converter.py`](backend/codebase_converter.py) | The full multi-pass translation pipeline (the project's largest and most novel component). |

### 6.3 Async job system

Long conversions run on a `threading.Thread` per job, tracked in an in-memory `_jobs` dict keyed by a short UUID, each with an `on_progress` callback. The frontend polls for status — no blocking requests, no external queue.

---

## 7. The RAG Pipeline (Codebase Q&A)

The goal is **grounded** answers — every claim traceable to real source.

```
Repo ──▶ parse_codebase (Tree-sitter AST)
         │   chunks at function / class granularity (not blind line-windows)
         ▼
       embed_chunks (nomic-embed-text)
         ▼
       chroma_store (ChromaDB vector DB, persisted locally)
         ▼
  Query ─▶ rag_query: top-5 semantic retrieval
         ▼
       prompt = [SYSTEM] + question + retrieved code blocks
         ▼
       codelens-qwen (Ollama) ──▶ answer + source citations (file + line range)
```

**Why AST-level chunking matters:** naive fixed-size chunking splits a function across two chunks, so neither is independently meaningful. Tree-sitter chunks on syntactic boundaries (whole functions/classes), so each retrieved chunk is self-contained and citable.

---

## 8. The Codebase Converter (Core Contribution)

Translating one file is easy. Translating a **whole project** is hard because correctness is a *cross-file* property: a method renamed in `Library` must be called by the right name in `Member`, a C++ class needs a `.h` header visible to every translation unit, an abstract parent must not import its children (circular import). A naive file-by-file LLM loop fails all of these.

CodeLens AI's converter is built on one governing principle:

> **Deterministic-First:** Anything that *can* be computed from the source deterministically *must* be — never left to the LLM, which drifts between runs. The LLM is used only for genuine translation, fenced inside a hard contract.

### 8.1 Pipeline overview

```
Auto-detect source language from file extensions

PASS 0    Project Analysis (LLM, one call)
          → JSON schema: class hierarchy, abstract flags, inheritance, deps, enums

PASS 0.5  Topological Sort  → dependencies first, main() last

[ Deterministic contract — computed from source, NOT the LLM: ]
          • Dependency graph     _build_source_deps / _build_cpp_deps
          • Required methods     _build_source_required_methods / _build_header_required_methods
          • Naming map           _build_source_naming / _build_deterministic_naming
          • Import paths          _build_import_map (relative paths)
          • Persistence methods   scanned & forced into required_methods

PASS 0.1  Translation contract assembled (deterministic data overrides LLM)

[ C++ target only ]
PASS 0.2  Header-skeleton pre-pass → skeleton .h into conversion memory
          so every .cpp can see its dependencies' interfaces

PASS 1    Per-file conversion loop (dependency order):
            • build PEER CALLABLE WHITELIST from already-converted files
            • convert_single_file (LLM)
            • completeness check (detects stub bodies + missing enums) → repair
            • inject persistence stubs / fix inheritance / fix call-site casing
            • Python: detect & repair f-string-ternary semantic bug

PASS 2    Stitch pass (reconcile the set as a whole)

[ C++ target only ]
PASS 2.5  _generate_cpp_headers (LLM, one call per .cpp)
          _inject_cpp_includes (deterministic, 40+ std:: patterns)

PASS 3    Per-file verification (bounded LLM audit) → targeted repair
          → re-run completeness on repaired files

PASS 4    Java: sanitize + inject imports

PASS 5    Postprocess: format → compile-check → repair loop (≤ 2 attempts)
```

### 8.2 Key innovations

- **Peer Callable Whitelist** — After each file is converted, its public methods are extracted (deterministically) and injected into the next file's prompt as an explicit *"you may ONLY call these methods"* list. This converts "here are some signatures, understand them" into a hard constraint, killing cross-file method-name hallucination at near-zero cost.
- **Signature-Based Memory** — Instead of dumping the first N lines of each peer (which is just imports + class header), `_extract_file_signatures` produces a compact interface: class declaration, fields, and every method signature with a few body lines. A 280-line class collapses to ~60 dense, relevant lines — so a `save_data` method at line 220 is actually *visible* to files that depend on it.
- **Primacy discipline** — Empirically, instructions at the *top* of a prompt are obeyed most. So ground-truth (inheritance hints, peer interfaces) goes first; LLM-generated "plans" are never placed before real data (doing so once caused a measurable regression where a hallucinated fact anchored the whole generation).
- **Domain-specific semantic checkers** — Some bugs are *syntactically valid but semantically wrong* and invisible to compilers (e.g. a Python f-string ternary that prints as literal text). The fix is a purpose-built regex checker + targeted repair, not a bigger general verifier.
- **Three-layer persistence defense** — `save_data`/`load_data` are protected by (1) forced required-methods, (2) completeness repair, (3) stub injection so the program at least *runs* instead of crashing.
- **C++ as a first-class target** — Header (`.h`) generation, `#include` injection, ODR rules, `#pragma once` placement, and namespace handling were added so C++ output actually compiles across translation units.

### 8.3 Quality / robustness layers

| Layer | Tooling per language |
|---|---|
| **Format** | Python `black` · TS/JS `prettier` · Java `prettier-plugin-java` · C++ `clang-format` |
| **Compile-check** | Python `pyflakes`+`py_compile` · TS `tsc --noEmit` · JS `node --check` · Java `javac` · C++ `g++ -fsyntax-only` |
| **Repair** | On compile failure, up to `MAX_REPAIR_ATTEMPTS = 2` targeted LLM repairs |

### 8.4 Language coverage

- **Source (full deterministic support):** C, C++, Java, Python, TypeScript, JavaScript.
- **Target:** Python, JavaScript, TypeScript, Java, C++.

### 8.5 Measured quality (benchmark history)

The flagship benchmark — translating a multi-file **LibrarySystem** from **C++ → Python** — was scored repeatedly against a hand-written reference (91/100):

| Version | Score | Breakthrough |
|---|---|---|
| v1–v3 | 38–52 | Empty shells, circular imports |
| v7 | 79 | Complete persistence |
| v8 | 82 | Inheritance correct |
| **v12 (current best)** | **87** | F-string ternaries, history methods, full 4-stage `load_data`, save-on-exit |

A second benchmark (**Java → C++ BankingSystem**) drove the C++-target header/enum/stub fixes, moving it from an initial 44/100 toward the 65–78 range after the structural pass.

---

## 9. Model / AI (`model/`)

### 9.1 Two-model strategy

| Role | Model | Notes |
|---|---|---|
| **Chat / RAG** | `codelens-qwen` | Qwen2.5-Coder **3B**, fine-tuned with **QLoRA**, exported to GGUF, served via a custom **Modelfile**. |
| **Conversion** | `qwen2.5-coder:7b` | Larger model for the converter — 3B hit a hard capacity ceiling on cross-file consistency; 7B fits in 4-bit (~4–5 GB VRAM) on an RTX 4060. |

Both are served by **Ollama** with `keep_alive: -1` (model stays resident). The Modelfile pins deterministic decoding for the converter use case (`temperature 0.1`, `top_p 0.9`, `repeat_penalty 1.1`, `num_ctx 4096`, ChatML stop tokens).

### 9.2 Fine-tuning

- **Method:** QLoRA (4-bit) on a single **RTX 4060**.
- **Constraints baked in:** `device_map={'':0}` (single-GPU required for 4-bit), `dataloader_num_workers=0` (Windows requirement), launched with `python -X utf8`.
- **Artifacts:** [`codelens_finetune.ipynb`](model/codelens_finetune.ipynb) (training), [`train_local.py`](model/train_local.py), [`merge_and_export.py`](model/merge_and_export.py) (LoRA merge → GGUF), [`bleu_eval.py`](model/bleu_eval.py) / [`test_baseline.py`](model/test_baseline.py) (evaluation), and the shipped `codelens-qwen-q4_k_m.gguf`.

### 9.3 Evaluation results

Measured on a 50-sample held-out set (BLEU + token-F1):

| Model | BLEU | Token-F1 |
|---|---|---|
| Base `qwen2.5-coder:3b` | 11.49 | 0.155 |
| **Fine-tuned `codelens-qwen`** | **65.06** | **0.617** |
| **Improvement** | **+53.56** | **+0.462** |

The fine-tune delivers a **~5.7×** BLEU improvement over the base model on the target task.

---

## 10. Dataset & Training Files (`dataset/`)

The training corpus is assembled by reproducible scripts ([`dataset/scripts/`](dataset/scripts/)):

| Script | Purpose |
|---|---|
| `download_codesearchnet.py` | Pull CodeSearchNet (code + natural-language docstrings). |
| `download_translation_pairs.py` | Pull cross-language code translation pairs. |
| `generate_translation_pairs.py` | Synthesize additional translation pairs. |
| `format_instruction_triples.py` | Convert raw data into instruction/prompt/response triples. |
| `mix_and_split_dataset.py` | Mix sources and produce train/eval splits. |

Data flows `dataset/data/raw → dataset/data/processed` (raw/processed payloads are git-ignored to keep the repo lean; the *scripts* are committed so the dataset is fully reproducible). Dataset prep is documented in [`model/notebooks/phase2_dataset_prep.ipynb`](model/notebooks/phase2_dataset_prep.ipynb).

---

## 11. Mathematical Foundations

### 11.1 Retrieval-Augmented Generation (RAG)

**Embedding**

Each code chunk `cᵢ` is mapped to a dense vector by the encoder:

```
eᵢ = Encoder(cᵢ) ∈ ℝ⁷⁶⁸
```

`nomic-embed-text` produces 768-dimensional embeddings. The same encoder is applied to the user query `q` to obtain `e_q`.

**Similarity retrieval**

Semantic similarity between the query and each stored chunk is measured by cosine similarity:

```
sim(e_q, eᵢ) = (e_q · eᵢ) / (‖e_q‖ · ‖eᵢ‖)
```

The top-5 chunks are selected by ranking all stored embeddings on this score:

```
C* = top-5 { sim(e_q, eᵢ) : eᵢ ∈ ChromaDB }
```

**Answer generation**

The LLM is conditioned on the retrieved context, not free to hallucinate:

```
answer = LLM( SYSTEM_PROMPT ⊕ query ⊕ C* )
```

where `⊕` denotes prompt concatenation. The model's output is thus grounded in `C*` — every claim traceable to a real source chunk.

---

### 11.2 Codebase Converter

**Topological ordering**

The project is modelled as a dependency graph `G = (V, E)` where `V` is the set of files and `(fᵢ, fⱼ) ∈ E` means `fⱼ` imports `fᵢ`. Kahn's algorithm computes a topological sort `τ` such that every file appears after all its dependencies:

```
τ = TopSort(G)    s.t.  fᵢ appears before fⱼ  whenever  (fᵢ, fⱼ) ∈ E
```

This guarantees the converter processes each file only after its dependencies are already translated.

**Peer Callable Whitelist**

Let `Mᵢ` be the set of public method signatures deterministically extracted from the already-converted output of file `fᵢ`. When converting file `fⱼ` that depends on `fᵢ`:

```
Prompt(fⱼ) = CONTRACT ⊕ WHITELIST(Mᵢ) ⊕ source(fⱼ)
```

The constraint injected into the prompt is hard: the LLM may **only** call methods in `Mᵢ`. This turns an informational hint into a verifiable constraint, eliminating cross-file method hallucination at zero additional LLM cost.

**Signature-based memory compression**

Raw peer files are too large to include verbatim in every prompt. `_extract_file_signatures` compresses each peer to its interface:

```
Compression ratio ≈ N_raw / N_sig  ≈  280 / 60  ≈  4.7×
```

This ensures that a method defined at line 220 of a 280-line file (e.g. `save_data`) is visible in the context of every file that depends on it, instead of being cut off by a naive first-N-lines window.

**Bounded repair loop**

After each conversion attempt, the output is passed to a language-specific compiler check. On failure:

```
repeat:
    fᵢ ← LLM_repair(fᵢ, errors)
    if compile_check(fᵢ) = PASS: break
until attempts ≥ MAX_REPAIR_ATTEMPTS  (= 2)
```

The bound prevents an infinite loop while still giving the model two targeted repair passes.

---

### 11.3 QLoRA Fine-Tuning

Standard full fine-tuning requires storing gradients and optimizer states proportional to the full weight matrix `W ∈ ℝᵐˣⁿ`, which is infeasible on a consumer GPU for a 3B-parameter model.

**Low-rank adaptation (LoRA)**

The weight update is decomposed into a product of two small matrices:

```
ΔW = A · B    where  A ∈ ℝᵐˣʳ,  B ∈ ℝʳˣⁿ,  rank r ≪ min(m, n)
```

The effective weight during training is:

```
W' = W + (α / r) · ΔW
```

where `α` is the LoRA scaling hyperparameter. `W` is frozen; only `A` and `B` are trained. The number of trainable parameters drops from `m × n` to `r × (m + n)`.

**4-bit NF4 quantization (QLoRA)**

The frozen base weights `W` are stored in 4-bit NormalFloat (NF4) format rather than 32-bit float:

```
Memory(W) ≈ (4 / 32) × Memory_fp32(W)  =  0.125 × baseline
```

Combined with LoRA, this allows training a 3B-parameter model within the 8 GB VRAM of a single RTX 4060.

---

### 11.4 Evaluation Metrics

**BLEU score**

BLEU measures n-gram overlap between the model's output and a reference translation:

```
BLEU = BP × exp( Σₙ wₙ × log pₙ )
```

where:
- `pₙ` = modified n-gram precision at order `n` = (matching n-grams in candidate) / (total n-grams in candidate)
- `wₙ` = 1/N with N = 4 (uniform weights across unigram to 4-gram)
- `BP` = brevity penalty = `min(1, exp(1 − r/c))`, penalising outputs shorter than the reference (`r` = reference length, `c` = candidate length)

**Token-F1**

Token-F1 treats each output as a bag of tokens and measures overlap symmetrically:

```
P  = |predicted_tokens ∩ reference_tokens| / |predicted_tokens|
R  = |predicted_tokens ∩ reference_tokens| / |reference_tokens|
F1 = 2PR / (P + R)
```

Unlike BLEU, Token-F1 does not penalise word order or length, making it a complementary signal.

**Observed results** (50-sample held-out set):

| Model | BLEU | Token-F1 |
|---|---|---|
| Base `qwen2.5-coder:3b` | 11.49 | 0.155 |
| **Fine-tuned `codelens-qwen`** | **65.06** | **0.617** |
| **Improvement** | **+53.56 (~5.7×)** | **+0.462** |

---

## 12. Technology Stack

| Layer | Technology |
|---|---|
| **Extension** | TypeScript, VS Code Extension API (chat participant, webviews), webpack |
| **Backend** | Python, FastAPI, Uvicorn, Pydantic |
| **LLM serving** | Ollama (local) |
| **Models** | Qwen2.5-Coder 3B (fine-tuned) + 7B; `nomic-embed-text` for embeddings |
| **Vector DB** | ChromaDB (persisted locally) |
| **Parsing** | Tree-sitter (Python, JS, TS, Java, C, C++, Rust, Go grammars) |
| **Training** | QLoRA / 4-bit, single RTX 4060 |
| **Quality tooling** | black, prettier, prettier-plugin-java, clang-format, pyflakes, tsc, javac, g++ |

---

## 13. Repository Structure

```
codelens-ai/
├── src/              # FRONTEND — VS Code extension (TypeScript)
│   ├── extension.ts  #   activation, server lifecycle, chat participant, commands
│   └── panels/       #   ChatPanel, ConverterPanel, GraphPanel (webviews)
│
├── backend/          # BACKEND — FastAPI server + pipelines
│   ├── fastapi_server.py      # REST API surface
│   ├── parse_codebase.py      # Tree-sitter chunking
│   ├── embed_chunks.py        # embeddings
│   ├── chroma_store.py        # vector store
│   ├── rag_query.py           # RAG retrieval + answer
│   ├── build_graph.py         # dependency graph
│   └── codebase_converter.py  # multi-pass translation pipeline
│
├── model/            # MODEL/AI — fine-tuning + evaluation
│   ├── codelens_finetune.ipynb
│   ├── train_local.py
│   ├── merge_and_export.py
│   ├── bleu_eval.py / test_baseline.py
│   ├── Modelfile
│   └── codelens-qwen-q4_k_m.gguf
│
├── dataset/          # DATASET — reproducible data scripts + splits
│   ├── scripts/      #   download / generate / format / mix
│   └── data/         #   raw → processed (payloads git-ignored)
│
├── tests/            # benchmarks & fixtures (LibrarySystem, test_cpp, test_convert.py)
├── package.json      # extension manifest (root — required by VS Code)
├── requirements.txt  # Python backend dependencies
└── README.md
```

---

## 14. How to Run

1. **Install prerequisites:** Python 3.10+, Node.js, and [Ollama](https://ollama.com). Pull/register the models (`codelens-qwen`, `qwen2.5-coder:7b`, `nomic-embed-text`).
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   npm install
   ```
3. **Start the backend** (the extension also does this automatically):
   ```bash
   python -X utf8 backend/fastapi_server.py   # serves on http://localhost:8080
   ```
4. **Launch the extension:** open the project in VS Code and press **F5** (Extension Development Host).
5. **Use it:**
   - `CodeLens AI: Index Current Workspace` to build the RAG index.
   - Ask `@codelens-ai` questions in chat.
   - `CodeLens AI: Open Code Converter` to translate a project.
   - `CodeLens AI: Open Dependency Graph` to explore architecture.

---

## 15. Design Principles (Summary)

1. **Offline by mandate** — no code ever leaves the machine; no external API is ever called.
2. **Deterministic-first** — compute everything computable; fence the LLM inside a hard contract.
3. **Whole-project reasoning** — schema + dependency graph + per-class callable contracts before generation.
4. **Ground truth before generation** — never let an LLM-generated "fact" precede real source in a prompt (primacy effect).
5. **Build specific checkers, not bigger verifiers** — semantic bugs invisible to compilers get purpose-built detectors.
6. **Fail soft** — stub injection and bounded repair loops keep output runnable even when a stage falls short.

---

## 16. Future Work

- **Rust / Go as conversion targets** (grammars already parsed for RAG; target rules + extensions pending).
- **Tightening C++ semantic translation** (serialization wire-format and generic-type erasure in the schema).
- **Namespace enforcement** beyond advisory.
- **Incremental re-indexing** so edits don't require a full re-index.
- **Streaming conversion progress** at sub-file granularity in the Converter panel.
```
