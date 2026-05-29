"""
Multi-file codebase converter.

Handles:
  - Single file translation (with full codebase context)
  - Entire directory/workspace translation
  - ZIP archive upload → translate all files → return ZIP

Preserves:
  - All function/class names and signatures
  - All logic and algorithms
  - Cross-file import references (rewritten for target language)
  - External dependency equivalents (+ dependency manifest generation)
"""

import io
import json
import os
import re
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Callable, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL",    "http://localhost:11434")
CONVERT_MODEL      = os.getenv("CONVERT_MODEL",      "qwen2.5-coder:3b")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "qwen2.5-coder:3b")

# ── Language ↔ extension maps ─────────────────────────────────────────────────
SOURCE_EXTENSIONS: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".java": "java",
    ".c":    "c",
    ".cpp":  "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".rs":   "rust",
    ".go":   "go",
}

TARGET_EXTENSIONS: dict[str, str] = {
    "python":     ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "java":       ".java",
    "c":          ".c",
    "cpp":        ".cpp",
    "rust":       ".rs",
    "go":         ".go",
}

SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "dist", "build", ".tmp", ".idea", ".vscode",
    "target", "vendor", ".gradle", ".mvn",
}

# ── Known external-library mappings (source_pkg → target_pkg) ─────────────────
# None = stdlib / built-in equivalent (no install needed)
_DEPS: dict[tuple[str, str], dict[str, Optional[str]]] = {
    ("python", "javascript"): {
        "requests": "axios", "httpx": "axios", "aiohttp": "axios",
        "flask": "express", "fastapi": "express", "uvicorn": "express",
        "sqlalchemy": "sequelize", "pymongo": "mongoose", "psycopg2": "pg",
        "pydantic": "zod", "marshmallow": "joi",
        "click": "commander", "argparse": None,
        "rich": "chalk", "colorama": "chalk",
        "redis": "ioredis", "celery": "bull",
        "boto3": "@aws-sdk/client-s3",
        "chromadb": "chromadb", "openai": "openai",
        "python-dotenv": "dotenv",
        "pytest": "jest", "unittest": "jest",
        "os": None, "sys": None, "json": None, "re": None,
        "math": None, "random": None, "time": None, "datetime": "moment",
        "pathlib": None, "logging": None, "typing": None,
        "dataclasses": None, "abc": None, "enum": None,
        "collections": None, "itertools": None, "functools": None,
        "asyncio": None, "threading": "worker_threads",
        "subprocess": "child_process", "shutil": "fs-extra",
        "io": None, "base64": None, "uuid": "uuid",
        "hashlib": "crypto", "hmac": "crypto",
    },
    ("python", "typescript"): {
        "requests": "axios", "httpx": "axios",
        "flask": "express", "fastapi": "express",
        "pydantic": "zod",
        "click": "commander",
        "redis": "ioredis",
        "chromadb": "chromadb", "openai": "openai",
        "python-dotenv": "dotenv",
        "pytest": "jest",
        "os": None, "sys": None, "json": None, "re": None,
        "math": None, "datetime": "moment", "pathlib": None,
        "typing": None, "dataclasses": None, "abc": None, "enum": None,
        "uuid": "uuid", "hashlib": "crypto",
    },
    ("python", "go"): {
        "requests": "net/http",
        "json": "encoding/json",
        "os": "os", "re": "regexp",
        "pathlib": "path/filepath",
        "logging": "log", "datetime": "time",
        "uuid": "github.com/google/uuid",
        "pydantic": None,
        "fastapi": "github.com/gin-gonic/gin",
        "redis": "github.com/redis/go-redis/v9",
        "chromadb": None, "openai": "github.com/sashabaranov/go-openai",
    },
    ("python", "rust"): {
        "requests": "reqwest",
        "json": "serde_json",
        "os": "std::env",
        "re": "regex",
        "logging": "log",
        "uuid": "uuid",
        "redis": "redis",
        "openai": "async-openai",
    },
    ("python", "java"): {
        "requests": "org.apache.httpcomponents:httpclient",
        "json": "org.json:json",
        "redis": "redis.clients:jedis",
        "openai": "com.theokanning.openai-gpt3-java:service",
        "pydantic": None,
        "uuid": None,
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def detect_language(path: Path) -> Optional[str]:
    return SOURCE_EXTENSIONS.get(path.suffix.lower())


def collect_files(root: Path, source_lang: Optional[str] = None) -> list[Path]:
    files = []
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        if any(part in SKIP_DIRS for part in f.relative_to(root).parts):
            continue
        lang = detect_language(f)
        if not lang:
            continue
        if source_lang and lang != source_lang:
            continue
        files.append(f)
    return files


def _extract_import_names(code: str, language: str) -> list[str]:
    """Regex-based import name extraction for dependency manifest building."""
    patterns = {
        "python": [
            r"^\s*import\s+([\w.]+)",
            r"^\s*from\s+([\w.]+)\s+import",
        ],
        "javascript": [r"""(?:import|require)\s*\(?['"]([^'"./][^'"]+)['"]"""],
        "typescript": [r"""(?:import|require)\s*\(?['"]([^'"./][^'"]+)['"]"""],
        "java":       [r"^\s*import\s+([\w.]+)\s*;"],
        "rust":       [r"^\s*(?:use|extern crate)\s+([\w:]+)"],
        "go":         [r'"([a-z][\w./]+)"'],
        "c":          [r'#include\s+[<"]([^>"]+)[>"]'],
        "cpp":        [r'#include\s+[<"]([^>"]+)[>"]'],
    }
    found = []
    for pat in patterns.get(language, []):
        for m in re.finditer(pat, code, re.MULTILINE):
            top = m.group(1).split(".")[0].split("/")[0]
            if top and top not in found:
                found.append(top)
    return found


def _build_context_block(files: list[Path], root: Path) -> str:
    """Compact file-tree summary (max ~60 entries) for prompt context."""
    lines = ["Repository file structure:"]
    shown = files[:60]
    for f in shown:
        lang = detect_language(f)
        rel  = f.relative_to(root).as_posix()
        lines.append(f"  {rel}  [{lang}]")
    if len(files) > 60:
        lines.append(f"  … and {len(files) - 60} more files")
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences the model may have added."""
    text = text.strip()
    # Remove opening fence (``` or ```python etc.)
    text = re.sub(r'^```[a-zA-Z0-9]*\s*\n?', '', text)
    # Remove any trailing closing fence — handles stray ``` at end of file
    text = re.sub(r'\n?```+\s*$', '', text)
    return text.strip()


def _extract_module_symbols(code: str, language: str) -> list[str]:
    """Extract top-level class/function names a file defines (for import map)."""
    patterns = {
        "python":     [r"^class\s+(\w+)", r"^def\s+(\w+)"],
        "javascript": [r"^(?:export\s+(?:default\s+)?)?(?:class|function\*?)\s+(\w+)",
                       r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:function|\(|async)"],
        "typescript": [r"^(?:export\s+(?:default\s+)?)?(?:class|function\*?|interface|type|enum|abstract\s+class)\s+(\w+)",
                       r"^(?:export\s+)?(?:const|let)\s+(\w+)\s*[=:]"],
        "java":       [r"^(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)"],
        "go":         [r"^func\s+(\w+)\s*\(", r"^type\s+(\w+)\s+(?:struct|interface)"],
        "rust":       [r"^(?:pub\s+)?(?:fn|struct|enum|trait|type)\s+(\w+)"],
        "c":          [r"^(?:typedef\s+)?struct\s+(\w+)"],
        "cpp":        [r"^(?:class|struct)\s+(\w+)"],
    }
    found = []
    for pat in patterns.get(language, []):
        for m in re.finditer(pat, code, re.MULTILINE):
            name = m.group(1)
            if name and name not in found and not name.startswith("_"):
                found.append(name)
    return found[:15]


def _import_statement(stem: str, syms: list[str], target_lang: str) -> str:
    """Return a ready-to-paste import line for target_lang."""
    name = stem.rsplit("/", 1)[-1]
    s    = ", ".join(syms)
    if target_lang == "python":
        return f"from .{name} import {s}"
    if target_lang in ("javascript",):
        return f'import {{ {s} }} from "./{stem}.js"'
    if target_lang == "typescript":
        return f'import {{ {s} }} from "./{stem}"'
    if target_lang == "java":
        return f"import {stem.replace('/', '.')};"
    if target_lang == "go":
        return f'import "./{stem}" // defines {s}'
    if target_lang == "rust":
        return f"use crate::{name.lower()}::{{{s}}};"
    return f"// from ./{stem}: {s}"


def _build_module_map(
    module_symbols: dict[str, list[str]],
    target_lang: str,
) -> str:
    """Return a prompt block with ready-to-paste import statements."""
    lines = ["MODULE MAP — paste these import lines at the top of the file as needed:"]
    for orig_rel, syms in sorted(module_symbols.items()):
        if not syms:
            continue
        stem = orig_rel.rsplit(".", 1)[0]
        lines.append(f"  {_import_statement(stem, syms, target_lang)}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _inject_project_imports(
    converted_code: str,
    source_code: str,
    target_lang: str,
    peer_output_stems: dict[str, list[str]],
) -> str:
    """
    Deterministically prepend missing project-internal imports.
    Never touches the class/function body — only prepends lines at the top.

    Adds an import for a peer module when:
      - At least one of its exported symbols is referenced in the source code
      - AND it is not already in the first 30 lines of the converted file
    """
    import_section = "\n".join(converted_code.splitlines()[:30]).lower()
    to_add = []

    for stem, syms in sorted(peer_output_stems.items()):
        if not syms:
            continue
        name = stem.rsplit("/", 1)[-1]

        # Symbol referenced in source?
        if not any(re.search(r'\b' + re.escape(sym) + r'\b', source_code) for sym in syms):
            continue

        # Already imported in converted file?
        if name.lower() in import_section or any(sym.lower() in import_section for sym in syms):
            continue

        to_add.append(_import_statement(stem, syms, target_lang))

    if not to_add:
        return converted_code
    return "\n".join(to_add) + "\n" + converted_code


def _fix_main_llm(
    main_code: str,
    peer_converted: dict[str, str],
    target_lang: str,
) -> str:
    """
    LLM-only pass for the main entry-point file.
    Shows it the real signatures of every converted module and tells it to
    import them instead of redefining classes inline.
    """
    map_lines = ["IMPORT THESE — do NOT redefine their classes inline:"]
    sig_parts  = []

    for out_path, code in sorted(peer_converted.items()):
        stem = out_path.rsplit(".", 1)[0]
        syms = _extract_module_symbols(code, target_lang)
        if not syms:
            continue
        map_lines.append(f"  {_import_statement(stem, syms, target_lang)}")
        preview = "\n".join(code.splitlines()[:35])
        sig_parts.append(f"// --- {out_path} ---\n{preview}")

    if len(map_lines) <= 1:
        return main_code

    prompt = (
        f"Fix this {target_lang} main/entry-point file. "
        f"All module files have already been correctly converted.\n\n"
        f"{chr(10).join(map_lines)}\n\n"
        f"CONVERTED MODULE SIGNATURES (first 35 lines each):\n"
        f"{chr(10).join(sig_parts[:6])}\n\n"
        f"CURRENT main file:\n"
        f"```{target_lang}\n{main_code[:4000]}\n```\n\n"
        f"STRICT RULES — every rule is mandatory:\n"
        f"1. Replace every inline class body that duplicates a module in the list above "
        f"   with the correct import statement instead.\n"
        f"2. Do NOT define DungeonMaster, Player, Login, Entity, or any other module class "
        f"   inline — IMPORT them from the files listed above.\n"
        f"3. Preserve all main() / game loop logic and keep it working.\n"
        f"4. Align all method/attribute call-sites to match the signatures shown above.\n"
        f"5. Output ONLY the complete fixed {target_lang} file. No fences. No explanation."
    )

    try:
        out = _call_model(prompt, CONVERT_MODEL)
        return _strip_fences(out)
    except Exception:
        return main_code


def _stitch_pass(
    results: dict[str, str],
    original_code: dict[str, str],
    source_lang: str,
    target_lang: str,
) -> dict[str, str]:
    """
    Two-step stitching that runs after all individual files are converted:

    Step 1 — Non-main files: deterministic import injection.
      No LLM involved. Looks at the source code to find which peer-module
      symbols are referenced, then prepends the correct import lines if they
      are missing.  The class body is NEVER touched.

    Step 2 — Main file only: LLM pass.
      Shows main the real signatures of every converted module and instructs
      it to import instead of redefining classes inline.
    """
    _IS_MAIN = lambda stem: stem.rsplit("/", 1)[-1].lower() in (
        "main", "__main__", "index", "app"
    )

    # Build out_stem → symbols from what was actually produced
    out_stem_syms: dict[str, list[str]] = {}
    for out_path, code in results.items():
        stem = out_path.rsplit(".", 1)[0]
        syms = _extract_module_symbols(code, target_lang)
        if syms:
            out_stem_syms[stem] = syms

    fixed:    dict[str, str] = {}
    main_key: Optional[str]  = None

    for out_path, code in results.items():
        stem = out_path.rsplit(".", 1)[0]

        if _IS_MAIN(stem):
            main_key = out_path
            fixed[out_path] = code   # handled in step 2
            continue

        # Find the matching source file
        base     = stem.rsplit("/", 1)[-1].lower()
        src_code = next(
            (src for src_rel, src in original_code.items()
             if src_rel.rsplit(".", 1)[0].rsplit("/", 1)[-1].lower() == base),
            ""
        )

        if not src_code:
            fixed[out_path] = code
            continue

        peer_stems = {s: v for s, v in out_stem_syms.items()
                      if s != stem and not _IS_MAIN(s)}

        fixed[out_path] = _inject_project_imports(
            code, src_code, target_lang, peer_stems
        )

    # Step 2: LLM fix for main only
    if main_key:
        peers = {p: fixed[p] for p in fixed if p != main_key}
        fixed[main_key] = _fix_main_llm(fixed[main_key], peers, target_lang)

    return fixed


# ── Core conversion call ──────────────────────────────────────────────────────

def _call_model(prompt: str, model: str, timeout: int = 300) -> str:
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "keep_alive": -1},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def convert_single_file(
    code: str,
    source_lang: str,
    target_lang: str,
    filename: str,
    codebase_context: str = "",
    import_graph: str = "",
    module_map: str = "",
) -> str:
    """
    Convert one source file to target_lang.
    codebase_context — compact file-tree for cross-file awareness.
    import_graph     — what this file imports (external deps).
    module_map       — what every other project file exports (for cross-imports).
    """
    ctx_block = ""
    if codebase_context:
        ctx_block = f"\n\n### CODEBASE STRUCTURE\n{codebase_context}"
    if module_map:
        ctx_block += f"\n\n### {module_map}"
    if import_graph:
        ctx_block += f"\n\n### THIS FILE'S SOURCE IMPORTS\n{import_graph}"

    is_main = filename.rsplit("/", 1)[-1].startswith("main")

    base_name = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    prompt = (
        f"You are an expert polyglot programmer translating a {source_lang} "
        f"codebase to {target_lang}.\n"
        f"\n"
        f"RULES — every rule is mandatory:\n"
        f"1. This file is '{filename}'. It MUST contain the full {base_name} class/module body. "
        f"   Do NOT produce an empty file or a file with only import statements.\n"
        f"2. Preserve ALL function/method/class names and public signatures.\n"
        f"3. Preserve ALL logic, algorithms, and control-flow exactly.\n"
        f"4. NEVER import from main.py, main.ts, main.go, or any entry-point file. "
        f"   Only import from peer modules listed in the MODULE MAP.\n"
        f"5. For third-party and stdlib imports use idiomatic {target_lang} equivalents.\n"
        f"6. Preserve all docstrings and comments.\n"
        f"7. Output ONLY the raw translated code — no markdown fences, no explanations.\n"
        + (f"8. This is the MAIN entry-point — import peer modules from the MODULE MAP "
           f"and wire them together. Do not redefine their classes inline.\n" if is_main else "")
        + f"{ctx_block}\n"
        f"\n"
        f"### FILE TO TRANSLATE: {filename}\n"
        f"```{source_lang}\n"
        f"{code[:6000]}\n"
        f"```\n"
        f"\n"
        f"{target_lang} translation:"
    )

    try:
        result = _call_model(prompt, CONVERT_MODEL)
    except Exception:
        result = _call_model(prompt, FALLBACK_LLM_MODEL)

    return _strip_fences(result)


# ── Dependency manifest generation ───────────────────────────────────────────

def _npm_pkg_json(packages: list[str], project_name: str = "converted-project") -> str:
    deps = {p: "latest" for p in sorted(packages) if p}
    return json.dumps({
        "name": project_name.lower().replace(" ", "-"),
        "version": "1.0.0",
        "description": "Converted by CodeLens AI",
        "main": "index.js",
        "scripts": {"start": "node index.js", "test": "jest"},
        "dependencies": deps,
        "devDependencies": {"jest": "latest"} if "jest" in deps else {},
    }, indent=2)


def _go_mod(packages: list[str], module_name: str = "example/converted") -> str:
    lines = [f"module {module_name}", "", "go 1.21", ""]
    ext = [p for p in packages if "/" in p]
    if ext:
        lines.append("require (")
        for p in sorted(ext):
            lines.append(f"\t{p} v0.0.0")
        lines.append(")")
    return "\n".join(lines)


def _cargo_toml(packages: list[str], project_name: str = "converted") -> str:
    lines = [
        f'[package]',
        f'name = "{project_name}"',
        'version = "0.1.0"',
        'edition = "2021"',
        '',
        '[dependencies]',
    ]
    for p in sorted(packages):
        lines.append(f'{p} = "*"')
    return "\n".join(lines)


def generate_dependency_manifest(
    all_source_code: dict[str, str],  # rel_path → original code
    source_lang: str,
    target_lang: str,
    project_name: str = "converted-project",
) -> Optional[tuple[str, str]]:
    """
    Returns (filename, content) for the target language's dependency file,
    or None if not applicable.
    """
    # Collect all external imports from source
    mapping = _DEPS.get((source_lang, target_lang), {})
    target_pkgs: set[str] = set()

    for code in all_source_code.values():
        for imp in _extract_import_names(code, source_lang):
            mapped = mapping.get(imp)
            if mapped is not None:       # None = built-in
                target_pkgs.add(mapped)

    if not target_pkgs:
        return None

    if target_lang in ("javascript", "typescript"):
        return "package.json", _npm_pkg_json(list(target_pkgs), project_name)
    elif target_lang == "go":
        return "go.mod", _go_mod(list(target_pkgs), f"example/{project_name}")
    elif target_lang == "rust":
        return "Cargo.toml", _cargo_toml(list(target_pkgs), project_name)
    return None


# ── Full codebase conversion ──────────────────────────────────────────────────

def convert_codebase(
    root: Path,
    target_lang: str,
    source_lang: Optional[str] = None,
    on_progress: Optional[Callable[[str, str, int, int], None]] = None,
) -> dict[str, str]:
    """
    Walk `root`, translate every source file.

    on_progress(rel_path, status, total, done_so_far)
      status ∈ {"converting", "done", "skipped", "error"}

    Returns dict  { output_relative_path: converted_code }
    """
    files = collect_files(root, source_lang)
    if not files:
        return {}

    # Sort so main.* is always converted last — it needs to import everything else
    def _sort_key(p: Path) -> int:
        stem = p.stem.lower()
        return 1 if stem in ("main", "__main__", "index", "app") else 0
    files = sorted(files, key=_sort_key)

    context = _build_context_block(files, root)
    target_ext = TARGET_EXTENSIONS.get(target_lang, ".txt")
    original_code: dict[str, str] = {}
    results:       dict[str, str] = {}

    # Pre-pass: extract exported symbols from every file so each file's prompt
    # knows exactly what the other modules define and how to import them.
    module_symbols: dict[str, list[str]] = {}
    for fpath in files:
        rel  = fpath.relative_to(root).as_posix()
        lang = detect_language(fpath) or source_lang or "python"
        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
            module_symbols[rel] = _extract_module_symbols(code, lang)
        except Exception:
            module_symbols[rel] = []

    module_map = _build_module_map(module_symbols, target_lang)

    for i, fpath in enumerate(files):
        rel        = fpath.relative_to(root).as_posix()
        lang       = detect_language(fpath) or source_lang or "python"
        parts      = rel.rsplit(".", 1)
        out_rel    = (parts[0] if len(parts) > 1 else rel) + target_ext

        if on_progress:
            on_progress(rel, "converting", len(files), i)

        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
            original_code[rel] = code

            if len(code.strip()) < 5:
                results[out_rel] = f"// Originally: {rel}\n"
                if on_progress:
                    on_progress(rel, "skipped", len(files), i + 1)
                continue

            # Per-file external import note (stdlib / third-party deps)
            imports = _extract_import_names(code, lang)
            import_note = f"This file imports: {', '.join(imports[:20])}" if imports else ""

            # Module map excluding this file itself
            own_rel = rel
            own_syms = module_symbols.pop(own_rel, [])
            this_map = _build_module_map(module_symbols, target_lang)
            module_symbols[own_rel] = own_syms  # restore

            converted = convert_single_file(
                code=code,
                source_lang=lang,
                target_lang=target_lang,
                filename=rel,
                codebase_context=context,
                import_graph=import_note,
                module_map=this_map,
            )
            results[out_rel] = converted

            if on_progress:
                on_progress(rel, "done", len(files), i + 1)

        except Exception as exc:
            err_comment = {
                "python":     f"# ERROR: {exc}",
                "javascript": f"// ERROR: {exc}",
                "typescript": f"// ERROR: {exc}",
                "java":       f"// ERROR: {exc}",
                "go":         f"// ERROR: {exc}",
                "rust":       f"// ERROR: {exc}",
                "c":          f"/* ERROR: {exc} */",
                "cpp":        f"/* ERROR: {exc} */",
            }.get(target_lang, f"# ERROR: {exc}")
            results[out_rel] = err_comment + "\n"

            if on_progress:
                on_progress(rel, "error", len(files), i + 1)

    # Stitch pass: deterministic import injection for modules + LLM fix for main
    if len(results) > 1:
        if on_progress:
            on_progress("(stitching imports…)", "converting", len(results) + 1, len(results))
        results = _stitch_pass(results, original_code, source_lang or "python", target_lang)
        if on_progress:
            on_progress("(stitching imports…)", "done", len(results) + 1, len(results) + 1)

    # Generate dependency manifest
    if original_code:
        manifest = generate_dependency_manifest(
            original_code,
            source_lang or "python",
            target_lang,
            project_name=root.name,
        )
        if manifest:
            filename, content = manifest
            results[filename] = content

    return results


# ── ZIP support ───────────────────────────────────────────────────────────────

def convert_from_zip(
    zip_bytes: bytes,
    target_lang: str,
    source_lang: Optional[str] = None,
    on_progress: Optional[Callable[[str, str, int, int], None]] = None,
) -> bytes:
    """
    Accept ZIP bytes → extract → translate → return output ZIP bytes.
    """
    with tempfile.TemporaryDirectory(prefix="codelens_") as tmpdir:
        src_dir = Path(tmpdir) / "source"
        src_dir.mkdir()

        # Safe extraction (no path traversal)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for member in zf.namelist():
                safe_name = member.lstrip("/").replace("..", "_")
                dest = src_dir / safe_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not member.endswith("/"):
                    dest.write_bytes(zf.read(member))

        converted = convert_codebase(
            root=src_dir,
            target_lang=target_lang,
            source_lang=source_lang,
            on_progress=on_progress,
        )

        # Determine output folder name
        top_items = list(src_dir.iterdir())
        if len(top_items) == 1 and top_items[0].is_dir():
            out_name = f"{top_items[0].name}_{target_lang}"
        else:
            out_name = f"converted_{target_lang}"

        return make_zip(converted, root_folder=out_name)


def make_zip(files: dict[str, str], root_folder: str = "converted") -> bytes:
    """Pack {rel_path: content} into a ZIP archive and return the bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files.items():
            zf.writestr(f"{root_folder}/{rel_path}", content)
    return buf.getvalue()


# ── In-memory job registry (used by fastapi_server) ──────────────────────────

_jobs: dict[str, dict] = {}


def start_job(fn: Callable, *args, **kwargs) -> str:
    """
    Run fn(*args, **kwargs) in a background thread.
    Returns a job_id that can be polled via get_job / download_job.
    """
    job_id = uuid.uuid4().hex[:10]
    _jobs[job_id] = {
        "status":   "running",
        "total":    0,
        "done":     0,
        "log":      [],     # list of {path, status}
        "zip":      None,   # bytes when complete
        "error":    None,
    }

    def _run():
        def _progress(path: str, status: str, total: int, done: int):
            _jobs[job_id]["total"] = total
            _jobs[job_id]["done"]  = done
            entry = {"path": path, "status": status}
            _jobs[job_id]["log"].append(entry)
            # Keep log bounded
            if len(_jobs[job_id]["log"]) > 500:
                _jobs[job_id]["log"] = _jobs[job_id]["log"][-200:]

        try:
            zip_bytes = fn(*args, on_progress=_progress, **kwargs)
            _jobs[job_id]["zip"]    = zip_bytes
            _jobs[job_id]["status"] = "done"
        except Exception as exc:
            _jobs[job_id]["error"]  = str(exc)
            _jobs[job_id]["status"] = "error"

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


def pop_job_zip(job_id: str) -> Optional[bytes]:
    j = _jobs.get(job_id)
    return j["zip"] if j else None
