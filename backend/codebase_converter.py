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
import shutil
import subprocess
import sys
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
CONVERT_MODEL      = os.getenv("CONVERT_MODEL",      "qwen2.5-coder:7b")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "qwen2.5-coder:7b")

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
    "cpp":        ".cpp",
}

SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "dist", "build", ".tmp", ".idea", ".vscode",
    "target", "vendor", ".gradle", ".mvn",
}

MAX_REPAIR_ATTEMPTS = 2

# Naming convention applied globally per target language in the translation contract.
_NAMING_CONVENTION: dict[str, str] = {
    "python":     (
        "snake_case — convert every camelCase identifier to snake_case: "
        "getMemberId→get_member_id, borrowBook→borrow_book, isAvailable→is_available, "
        "canBorrow→can_borrow, checkoutBook→checkout_book, returnBook→return_book, "
        "hasBorrowed→has_borrowed, getBorrowedIsbns→get_borrowed_isbns, "
        "listAllBooks→list_all_books, addMember→add_member, showStats→show_stats"
    ),
    "javascript": "camelCase — keep camelCase as-is, do not convert to snake_case",
    "typescript": "camelCase — keep camelCase as-is, do not convert to snake_case",
    "java":       "camelCase — keep camelCase as-is, do not convert to snake_case",
    "cpp":        "camelCase — preserve original style",
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


# ── Pass 0: Project Analysis ──────────────────────────────────────────────────

def _analyze_project(files: list[Path], root: Path, source_lang: str) -> dict:
    """
    One model call on the entire source tree.
    Returns {"classes": {...}, "dependencies": {...}} or {} on failure.
    The schema is language-agnostic — it describes the source structure so
    every target-language conversion can make correct access/abstract decisions.
    """
    MAX_TOTAL_CHARS = 8000
    FILE_EXCERPT    = 300   # chars per file when total is too large

    file_contents: list[tuple[str, str]] = []
    for fpath in files:
        rel = fpath.relative_to(root).as_posix()
        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
            file_contents.append((rel, code))
        except Exception:
            pass

    if not file_contents:
        return {}

    total_chars = sum(len(c) for _, c in file_contents)
    parts = []
    for rel, code in file_contents:
        excerpt = code if total_chars <= MAX_TOTAL_CHARS else code[:FILE_EXCERPT]
        parts.append(f"--- {rel} ---\n{excerpt}")
    source_block = "\n\n".join(parts)

    prompt = (
        f"You are an expert static code analyzer specializing in {source_lang} OOP structure extraction.\n"
        f"Analyze this {source_lang} codebase and return ONLY a JSON object — "
        f"no explanation, no markdown fences.\n\n"
        f"Required JSON structure:\n"
        f'{{\n'
        f'  "classes": {{\n'
        f'    "ClassName": {{\n'
        f'      "abstract": true,\n'
        f'      "abstract_methods": ["methodName"],\n'
        f'      "protected_fields": ["fieldName"],\n'
        f'      "inherits": "ParentName or null"\n'
        f'    }}\n'
        f'  }},\n'
        f'  "enums": {{\n'
        f'    "ClassName.EnumName": ["VALUE1", "VALUE2", "VALUE3"]\n'
        f'  }},\n'
        f'  "dependencies": {{\n'
        f'    "filename.ext": ["dep1.ext", "dep2.ext"]\n'
        f'  }}\n'
        f'}}\n\n'
        f"Rules:\n"
        f"- abstract: true if the class has pure virtual methods (= 0) or is abstract\n"
        f"- abstract_methods: names of pure virtual / abstract methods\n"
        f"- protected_fields: fields that subclasses access directly (not via getters)\n"
        f"- inherits: direct parent class name, or null\n"
        f"- enums: for every enum type defined in the codebase, key = 'ContainingClass.EnumName' "
        f"(or just 'EnumName' for top-level enums), value = ALL enum values in order\n"
        f"- dependencies: for each file, list only OTHER project files it imports/includes\n\n"
        f"SOURCE FILES:\n{source_block}\n\n"
        f"JSON:"
    )

    try:
        raw = _call_model(prompt, CONVERT_MODEL, timeout=120)
        m = re.search(r'\{[\s\S]*\}', raw)
        if not m:
            return {}
        return json.loads(m.group(0))
    except Exception:
        return {}


def _topological_sort(files: list[Path], root: Path, schema: dict) -> list[Path]:
    """
    Order files so every dependency comes before its dependents.
    Main/index/app files are always placed last.
    Falls back to the original sort (main last, rest as-is) if schema lacks
    dependency data or contains cycles.
    """
    from collections import deque

    _IS_MAIN = lambda p: p.stem.lower() in ("main", "__main__", "index", "app")

    deps_map = schema.get("dependencies", {})
    if not deps_map:
        return sorted(files, key=lambda p: 1 if _IS_MAIN(p) else 0)

    rel_to_path = {f.relative_to(root).as_posix(): f for f in files}

    in_degree:  dict[str, int]       = {rel: 0 for rel in rel_to_path}
    dependents: dict[str, list[str]] = {rel: [] for rel in rel_to_path}

    for rel, deps in deps_map.items():
        if rel not in in_degree:
            continue
        for dep in deps:
            if dep in dependents:
                dependents[dep].append(rel)
                in_degree[rel] = in_degree.get(rel, 0) + 1

    queue = deque(
        rel for rel, deg in in_degree.items()
        if deg == 0 and not _IS_MAIN(rel_to_path[rel])
    )
    ordered: list[str] = []

    while queue:
        rel = queue.popleft()
        ordered.append(rel)
        for dep_rel in dependents.get(rel, []):
            in_degree[dep_rel] -= 1
            if in_degree[dep_rel] == 0 and not _IS_MAIN(rel_to_path.get(dep_rel, Path(dep_rel))):
                queue.append(dep_rel)

    seen = set(ordered)
    for rel in rel_to_path:
        if rel not in seen and not _IS_MAIN(rel_to_path[rel]):
            ordered.append(rel)

    for rel in rel_to_path:
        if _IS_MAIN(rel_to_path[rel]):
            ordered.append(rel)

    return [rel_to_path[rel] for rel in ordered if rel in rel_to_path]


def _schema_context_block(schema: dict, current_file: str) -> str:
    """
    Format the project schema as a human-readable prompt block.
    Gives the model the class hierarchy, abstract/protected decisions,
    and file dependencies so it can make correct structural choices.
    """
    if not schema:
        return ""

    lines = ["PROJECT SCHEMA — use this to make correct access/abstract/inheritance decisions:"]

    for cls_name, info in schema.get("classes", {}).items():
        flags = []
        if info.get("abstract"):
            flags.append("ABSTRACT class")
        parent = info.get("inherits")
        if parent:
            flags.append(f"extends {parent}")
        abs_methods = info.get("abstract_methods", [])
        if abs_methods:
            flags.append(f"abstract methods: {', '.join(abs_methods)}")
        prot = info.get("protected_fields", [])
        if prot:
            flags.append(f"protected fields: {', '.join(prot)}")
        label = " | ".join(flags) if flags else "concrete"
        lines.append(f"  {cls_name}: {label}")

    dep_lines = []
    for fname, dep_list in schema.get("dependencies", {}).items():
        if dep_list and fname != current_file:
            dep_lines.append(f"  {fname} → {', '.join(dep_list)}")
    if dep_lines:
        lines.append("\nFILE DEPENDENCIES (import graph):")
        lines.extend(dep_lines)

    return "\n".join(lines)


def _memory_block(
    conversion_memory: dict[str, str],
    current_deps: list[str],
    target_lang: str,
) -> str:
    """
    Format already-converted peer files as a compact signature block.
    Uses signature extraction instead of raw line slices — shows every
    method signature + a few body lines to reveal data formats and
    persistence schemas. Direct deps get 6 body lines; peers get 3.
    Max 8 files total.
    """
    if not conversion_memory:
        return ""

    MAX_FILES = 8

    dep_stems = {d.rsplit(".", 1)[0].rsplit("/", 1)[-1].lower() for d in current_deps}

    priority: list[str] = []
    for out_path in conversion_memory:
        out_stem = out_path.rsplit(".", 1)[0].rsplit("/", 1)[-1].lower()
        if out_stem in dep_stems and out_path not in priority:
            priority.append(out_path)

    for out_path in reversed(list(conversion_memory)):
        if len(priority) >= MAX_FILES:
            break
        if out_path not in priority:
            priority.append(out_path)

    lines = ["PEER MODULE INTERFACES — match these exact signatures, field names, and data formats:"]
    for out_path in priority[:MAX_FILES]:
        code     = conversion_memory[out_path]
        out_stem = out_path.rsplit(".", 1)[0].rsplit("/", 1)[-1].lower()
        body_n   = 6 if out_stem in dep_stems else 3
        sigs     = _extract_file_signatures(code, target_lang, body_lines=body_n)
        if sigs.strip():
            lines.append(f"--- {out_path} ---\n{sigs}")

    return "\n".join(lines)


def _build_peer_callable_methods(
    conversion_memory: dict[str, str],
    current_deps: list[str],
    target_lang: str,
    out_path_map: dict[str, str],
) -> dict[str, list[str]]:
    """
    Build {ClassName: [method_names]} from already-converted peer output files.
    Only covers direct dependencies — the classes this file actually instantiates
    and calls methods on. Used to inject a strict per-class callable-method
    whitelist into the generation prompt, preventing the model from inventing
    methods that don't exist on peer objects (e.g. member.show_member_history()).
    """
    extractor_map = {
        "python":     _extract_python_public_methods,
        "java":       _extract_java_public_methods,
        "javascript": _extract_ts_public_methods,
        "typescript": _extract_ts_public_methods,
    }
    extractor = extractor_map.get(target_lang)
    if not extractor:
        return {}

    result: dict[str, list[str]] = {}
    for dep_src in current_deps:
        out_rel = out_path_map.get(dep_src)
        if not out_rel or out_rel not in conversion_memory:
            continue
        code       = conversion_memory[out_rel]
        class_name = Path(out_rel).stem
        methods    = extractor(code, class_name)
        if methods:
            result[class_name] = methods

    return result


def _generate_translation_contract(
    files: list[Path],
    root: Path,
    source_lang: str,
    target_lang: str,
    schema: dict,
    target_ext: str,
    out_path_map: dict[str, str],  # src_rel → out_rel
) -> dict:
    """
    Pass 0.1 — one model call that locks in every cross-file decision.

    Returns:
    {
      "naming": {"ClassName.sourceSymbol": "targetName"},
      "required_methods": {"out/file.ext": ["targetMethod1", ...]},
      "abstract_classes": ["ClassName"],
      "concrete_classes": ["ClassName"],
    }
    Falls back to {} on any failure; callers degrade gracefully.
    """
    MAX_SOURCE_CHARS = 6000
    FILE_EXCERPT     = 600

    parts_list: list[str] = []
    total = 0
    for fpath in files:
        rel = fpath.relative_to(root).as_posix()
        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
            budget = FILE_EXCERPT if total > MAX_SOURCE_CHARS // 2 else 1000
            exc = code[:budget]
            parts_list.append(f"--- {rel} ---\n{exc}")
            total += len(exc)
        except Exception:
            pass

    source_block = "\n\n".join(parts_list)

    file_mapping = "\n".join(f"  {s} → {o}" for s, o in out_path_map.items())

    naming_rule = _NAMING_CONVENTION.get(target_lang, "camelCase")

    classes_summary = []
    for cls_name, info in schema.get("classes", {}).items():
        methods  = info.get("abstract_methods", [])
        parent   = info.get("inherits")
        is_abs   = info.get("abstract", False)
        classes_summary.append(
            f"  {cls_name}: abstract={is_abs}, parent={parent}, "
            f"abstract_methods={methods}"
        )
    schema_str = "\n".join(classes_summary) or "(no schema)"

    prompt = (
        f"You are an expert {source_lang}-to-{target_lang} migration engineer.\n"
        f"Create a translation contract for converting {source_lang} → {target_lang}.\n"
        f"This JSON is given to EVERY file during conversion so all files agree.\n\n"
        f"NAMING RULE: {naming_rule}\n\n"
        f"CLASS SCHEMA:\n{schema_str}\n\n"
        f"FILE MAPPING (source → output path):\n{file_mapping}\n\n"
        f"SOURCE CODE EXCERPTS:\n{source_block}\n\n"
        f"Return ONLY a JSON object — no markdown, no explanation:\n"
        f'{{\n'
        f'  "naming": {{\n'
        f'    "ClassName.sourceSymbol": "targetName"\n'
        f'  }},\n'
        f'  "required_methods": {{\n'
        f'    "output/file{target_ext}": ["targetMethod1", "targetMethod2"]\n'
        f'  }},\n'
        f'  "abstract_classes": ["OnlyTruelyAbstractClasses"],\n'
        f'  "concrete_classes": ["EverythingElse"]\n'
        f'}}\n\n'
        f"RULES — every rule is mandatory:\n"
        f"1. naming: apply the NAMING RULE to ALL public methods and fields for ALL classes.\n"
        f"   Include EVERY public method. Example for Python target:\n"
        f'     "Member.getMemberId": "get_member_id"\n'
        f'     "Member.borrowBook": "borrow_book"\n'
        f'     "Library.checkoutBook": "checkout_book"\n'
        f"2. required_methods: use the OUTPUT file path as key; list target-language names\n"
        f"   of ALL public methods that file's class must implement. Be exhaustive.\n"
        f"3. abstract_classes: ONLY classes with pure-virtual / abstract methods in source.\n"
        f"   Member is NOT abstract even if it looks like it. Check the schema.\n"
        f"4. concrete_classes: everything else including subclasses.\n\n"
        f"JSON:"
    )

    try:
        raw = _call_model(prompt, CONVERT_MODEL, timeout=180)
        m = re.search(r'\{[\s\S]*\}', raw)
        if not m:
            return {}
        obj = json.loads(m.group(0))
        # Scrub any placeholder keys the model left in
        for bad in ("ClassName.sourceSymbol", "OnlyTruelyAbstractClasses", "EverythingElse"):
            obj.get("naming", {}).pop(bad, None)
            for lst_key in ("abstract_classes", "concrete_classes"):
                if bad in obj.get(lst_key, []):
                    obj[lst_key].remove(bad)
        return obj
    except Exception:
        return {}


def _compute_python_relative_import(
    from_out: str, to_out: str, symbols: list[str]
) -> str:
    """
    Compute a correct Python relative import.
      from_out: "LibrarySystem/FictionBook.py"
      to_out:   "Colors.py"  →  from ..Colors import RED, GREEN, ...
      to_out:   "LibrarySystem/Book.py"  →  from .Book import Book
    """
    from_dir   = Path(from_out).parent
    to_path    = Path(to_out)
    to_stem    = to_path.stem
    to_dir     = to_path.parent

    from_parts = from_dir.parts if str(from_dir) != "." else ()
    to_parts   = to_dir.parts   if str(to_dir)   != "." else ()

    common = 0
    for a, b in zip(from_parts, to_parts):
        if a == b:
            common += 1
        else:
            break

    ups   = len(from_parts) - common
    downs = to_parts[common:]

    if ups == 0 and not downs:
        pkg = f".{to_stem}"
    elif ups == 0 and downs:
        pkg = "." + ".".join(downs) + f".{to_stem}"
    else:
        dots = "." * (ups + 1)
        pkg  = dots + (".".join(downs) + "." if downs else "") + to_stem

    sym_str = ", ".join(symbols) if symbols else to_stem
    return f"from {pkg} import {sym_str}"


def _build_import_map(
    files: list[Path],
    root: Path,
    schema: dict,
    target_lang: str,
    target_ext: str,
    module_symbols: dict[str, list[str]],
    synth_out_map: dict[str, str],
) -> dict[str, list[str]]:
    """
    Deterministically compute exact import statements for every output file
    using the schema dependency graph and output file layout.
    Returns {out_rel: [import_stmt, ...]}.
    """
    src_to_out: dict[str, str] = {}
    for fpath in files:
        src_rel = fpath.relative_to(root).as_posix()
        parts   = src_rel.rsplit(".", 1)
        out_rel = (parts[0] if len(parts) > 1 else src_rel) + target_ext
        src_to_out[src_rel] = out_rel
    src_to_out.update(synth_out_map)

    deps_map   = schema.get("dependencies", {})
    import_map: dict[str, list[str]] = {}

    for src_rel, out_rel in src_to_out.items():
        deps  = deps_map.get(src_rel, [])
        stmts: list[str] = []

        for dep_src in deps:
            dep_out  = src_to_out.get(dep_src)
            if not dep_out:
                continue
            dep_syms = module_symbols.get(dep_src, [])
            dep_stem = Path(dep_out).stem

            if target_lang == "python":
                stmt = _compute_python_relative_import(out_rel, dep_out, dep_syms)
                stmts.append(stmt)

            elif target_lang == "javascript":
                rel = os.path.relpath(dep_out, str(Path(out_rel).parent)).replace("\\", "/")
                if not rel.startswith("."):
                    rel = "./" + rel
                sym_str = ", ".join(dep_syms) if dep_syms else dep_stem
                stmts.append(f'import {{ {sym_str} }} from "{rel}"')

            elif target_lang == "typescript":
                dep_no_ext = dep_out.rsplit(".", 1)[0]
                rel = os.path.relpath(dep_no_ext, str(Path(out_rel).parent)).replace("\\", "/")
                if not rel.startswith("."):
                    rel = "./" + rel
                sym_str = ", ".join(dep_syms) if dep_syms else dep_stem
                stmts.append(f'import {{ {sym_str} }} from "{rel}"')

            elif target_lang == "java":
                dep_dir = str(Path(dep_out).parent).replace("/", ".").replace("\\", ".")
                out_dir = str(Path(out_rel).parent).replace("/", ".").replace("\\", ".")
                if dep_dir and dep_dir != "." and dep_dir != out_dir:
                    for sym in (dep_syms or [dep_stem]):
                        stmts.append(f"import {dep_dir}.{sym};")

        if stmts:
            import_map[out_rel] = stmts

    return import_map


def _build_cpp_deps(
    files: list[Path],
    root: Path,
    synth_out_map: dict[str, str],
) -> dict[str, list[str]]:
    """
    Build a complete dependency graph for C/C++ projects by parsing #include "..."
    directives instead of asking a model. Reliable because it reads the actual source.
    Returns {src_rel: [dep_src_rel, ...]} covering every file.
    """
    # Map lowercase stem → canonical src_rel for every project file + synthesized header
    stem_to_rel: dict[str, str] = {}
    for fpath in files:
        rel = fpath.relative_to(root).as_posix()
        stem_to_rel[fpath.stem.lower()] = rel
    for h_rel in synth_out_map:
        stem_to_rel[Path(h_rel).stem.lower()] = h_rel

    def _read_includes(path: Path) -> list[str]:
        """Return all quoted #include stems from a single file."""
        try:
            code = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
        return re.findall(r'#include\s+"([^"]+)"', code)

    deps: dict[str, list[str]] = {}
    for fpath in files:
        rel  = fpath.relative_to(root).as_posix()
        # Collect includes from the .cpp file itself AND its matching .h header
        # (one level deep) so transitive deps like Library.cpp→Library.h→Member.h
        # are captured without a full recursive walk.
        raw_includes = _read_includes(fpath)
        h_peer = fpath.with_suffix(".h")
        if h_peer.exists():
            raw_includes += _read_includes(h_peer)

        file_deps: list[str] = []
        for inc in raw_includes:
            dep_stem = Path(inc).stem.lower()
            dep_rel  = stem_to_rel.get(dep_stem)
            if dep_rel and dep_rel != rel and dep_rel not in file_deps:
                file_deps.append(dep_rel)
        deps[rel] = file_deps

    return deps


def _extract_cpp_public_methods(h_code: str) -> list[str]:
    """
    Parse the public method names from a C++ header file.
    Returns method names as-is (source language casing) — callers apply naming conversion.
    Destructors and constructors are excluded; use _cpp_has_constructor separately.
    """
    methods: list[str] = []
    in_public = False
    for line in h_code.splitlines():
        stripped = line.strip()
        if stripped.startswith("public:"):
            in_public = True
        elif stripped.startswith("private:") or stripped.startswith("protected:"):
            in_public = False
        elif in_public and stripped and not stripped.startswith("//"):
            # Skip destructors — they start with ~ (optionally after virtual)
            if re.match(r"(?:virtual\s+)?~", stripped):
                continue
            # Match: [virtual] ReturnType methodName(...)
            m = re.match(
                r"(?:virtual\s+)?(?:[\w:<>*&]+\s+)+(\w+)\s*\(",
                stripped,
            )
            if m:
                name = m.group(1)
                if name not in ("if", "while", "for", "switch", "return"):
                    methods.append(name)
    return methods


def _cpp_has_constructor(h_code: str, class_name: str) -> bool:
    """Return True if the C++ header declares a constructor in the public section."""
    in_public = False
    pattern = re.compile(rf"^{re.escape(class_name)}\s*\(")
    for line in h_code.splitlines():
        stripped = line.strip()
        if stripped.startswith("public:"):
            in_public = True
        elif stripped.startswith(("private:", "protected:")):
            in_public = False
        elif in_public and pattern.match(stripped):
            return True
    return False


def _to_snake_case(name: str) -> str:
    """Convert camelCase / PascalCase to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


# ── Source-language method extractors (non-C/C++) ─────────────────────────────

def _extract_java_public_methods(code: str, class_name: str) -> list[str]:
    """Parse public method names from a Java source file."""
    methods: list[str] = []
    # Match: public [static] [abstract] [final] ReturnType methodName(
    pattern = re.compile(
        r'^\s*public\s+'
        r'(?:(?:static|abstract|final|synchronized|default)\s+)*'
        r'(?:<[^>]+>\s+)?'          # optional generic return type
        r'(?:[\w<>\[\],\s]+?\s+)'   # return type (non-greedy)
        r'(\w+)\s*\(',
        re.MULTILINE,
    )
    keywords = {"if", "while", "for", "switch", "return", "new", "catch", "try"}
    for m in pattern.finditer(code):
        name = m.group(1)
        if name != class_name and name not in keywords:
            methods.append(name)
    return list(dict.fromkeys(methods))


def _extract_python_public_methods(code: str, class_name: str) -> list[str]:
    """Parse public method names from a Python source file (class body only)."""
    methods: list[str] = []
    in_class    = False
    class_indent = -1

    for line in code.splitlines():
        stripped = line.lstrip()
        indent   = len(line) - len(stripped)

        if not in_class:
            if re.match(rf'class\s+{re.escape(class_name)}\s*[:(]', stripped):
                in_class     = True
                class_indent = indent
            continue

        # Left the class body
        if stripped and not stripped.startswith("#") and indent <= class_indent:
            break

        m = re.match(r'def\s+(\w+)\s*\(', stripped)
        if m:
            name = m.group(1)
            if not name.startswith("_") or name == "__init__":
                methods.append(name)

    return list(dict.fromkeys(methods))


def _extract_ts_public_methods(code: str, class_name: str) -> list[str]:
    """Parse public method names from a TypeScript or JavaScript source file."""
    methods: list[str] = []
    in_class    = False
    brace_depth = 0
    keywords    = {
        "if", "while", "for", "switch", "return", "new", "super",
        "this", "catch", "try", "function", "class", "constructor",
        "const", "let", "var", "import", "export", "abstract", "override",
    }

    for line in code.splitlines():
        stripped = line.strip()

        if not in_class:
            if re.search(rf'\bclass\s+{re.escape(class_name)}\b', line):
                in_class    = True
                brace_depth = line.count("{") - line.count("}")
            continue

        brace_depth += line.count("{") - line.count("}")
        if brace_depth <= 0:
            break

        # Skip explicitly private/protected lines
        if re.match(r"(private|protected)\b", stripped):
            continue

        # Match: [public] [static] [async] [override] methodName(
        m = re.match(
            r"^(?:(?:public|static|async|override|abstract|readonly)\s+)*"
            r"(\w+)\s*\(",
            stripped,
        )
        if m:
            name = m.group(1)
            if name not in keywords and not name.startswith("_"):
                methods.append(name)

    return list(dict.fromkeys(methods))


_SNAKE_TARGETS = {"python"}


def _build_header_required_methods(
    files: list[Path],
    root: Path,
    target_lang: str,
    out_path_map: dict[str, str],
) -> dict[str, list[str]]:
    """
    Build required_methods from actual C++ .h header files.
    Returns {out_rel: [target_method_name, ...]} so the completeness checker
    knows exactly which methods every output file must implement.
    """
    req: dict[str, list[str]] = {}

    for fpath in files:
        # Find the matching .h file alongside this .cpp
        h_path = fpath.with_suffix(".h")
        if not h_path.exists():
            # Also try the .h in the same directory with the same stem
            h_path = fpath.parent / (fpath.stem + ".h")
        if not h_path.exists():
            continue
        try:
            h_code = h_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        src_rel = fpath.relative_to(root).as_posix()
        out_rel = out_path_map.get(src_rel)
        if not out_rel:
            continue

        methods = _extract_cpp_public_methods(h_code)

        if target_lang in _SNAKE_TARGETS:
            methods = [_to_snake_case(m) for m in methods]

        # Prepend constructor if the header declares one
        class_match = re.search(r"class\s+(\w+)", h_code)
        if class_match and _cpp_has_constructor(h_code, class_match.group(1)):
            ctor = "__init__" if target_lang == "python" else class_match.group(1)
            if ctor not in methods:
                methods = [ctor] + methods

        if not methods:
            continue

        req[out_rel] = methods

    return req


_CTOR_TARGET: dict[str, str] = {
    "python": "__init__",
    "javascript": "constructor",
    "typescript": "constructor",
}
_DTOR_TARGET: dict[str, str] = {
    "python": "__del__",
}


def _build_deterministic_naming(
    files: list[Path],
    root: Path,
    schema: dict,
    target_lang: str,
) -> dict[str, str]:
    """
    Build naming map from C++ .h headers + schema fields — deterministic, no LLM.
    Returns {"ClassName.cppName": "targetName"} for every public method and renamed field.
    Only activates for source files that have a matching .h header.
    """
    naming: dict[str, str] = {}
    do_snake = target_lang in _SNAKE_TARGETS

    for fpath in files:
        h_path = fpath.with_suffix(".h")
        if not h_path.exists():
            h_path = fpath.parent / (fpath.stem + ".h")
        if not h_path.exists():
            continue
        try:
            h_code = h_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        class_match = re.search(r"class\s+(\w+)", h_code)
        if not class_match:
            continue
        class_name = class_match.group(1)

        # Constructor
        if _cpp_has_constructor(h_code, class_name):
            ctor = _CTOR_TARGET.get(target_lang, class_name)
            naming[f"{class_name}.{class_name}"] = ctor

        # Destructor
        dtor = _DTOR_TARGET.get(target_lang)
        if dtor:
            naming[f"{class_name}.~{class_name}"] = dtor

        # Regular public methods
        for method in _extract_cpp_public_methods(h_code):
            target_name = _to_snake_case(method) if do_snake else method
            naming[f"{class_name}.{method}"] = target_name

    # Field renames from schema (only entries that actually change name)
    for cls_name, cls_info in schema.get("classes", {}).items():
        all_fields = cls_info.get("protected_fields", []) + cls_info.get("fields", [])
        for field in all_fields:
            target_field = _to_snake_case(field) if do_snake else field
            if field != target_field:
                naming[f"{cls_name}.{field}"] = target_field

    return naming


# ── Generalised source analysis (non-C/C++) ───────────────────────────────────

_SOURCE_EXTRACTORS = {
    "java":       _extract_java_public_methods,
    "python":     _extract_python_public_methods,
    "javascript": _extract_ts_public_methods,
    "typescript": _extract_ts_public_methods,
}


def _build_source_deps(
    files: list[Path],
    root: Path,
    source_lang: str,
) -> dict[str, list[str]]:
    """
    Build dependency graph for non-C/C++ source by parsing import statements.
    Returns {src_rel: [dep_src_rel, ...]} for every file.
    """
    stem_to_rel: dict[str, str] = {
        fpath.stem.lower(): fpath.relative_to(root).as_posix()
        for fpath in files
    }

    patterns: dict[str, list[str]] = {
        "python":     [r"^\s*from\s+\.(\w+)\s+import", r"^\s*import\s+(\w+)"],
        "javascript": [r'["\']\.\.?/(\w+)'],
        "typescript": [r'["\']\.\.?/(\w+)'],
        "java":       [r"import\s+(?:[\w]+\.)*(\w+)\s*;"],
    }
    pats = patterns.get(source_lang, [])

    deps: dict[str, list[str]] = {}
    for fpath in files:
        rel = fpath.relative_to(root).as_posix()
        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            deps[rel] = []
            continue
        file_deps: list[str] = []
        for pat in pats:
            for m in re.finditer(pat, code, re.MULTILINE):
                dep_stem = m.group(1).lower()
                dep_rel  = stem_to_rel.get(dep_stem)
                if dep_rel and dep_rel != rel and dep_rel not in file_deps:
                    file_deps.append(dep_rel)
        deps[rel] = file_deps
    return deps


def _build_source_required_methods(
    files: list[Path],
    root: Path,
    source_lang: str,
    target_lang: str,
    out_path_map: dict[str, str],
) -> dict[str, list[str]]:
    """
    Build required_methods by extracting public methods from source files directly.
    Works for Java, Python, TypeScript, JavaScript source.
    """
    extractor = _SOURCE_EXTRACTORS.get(source_lang)
    if not extractor:
        return {}

    do_snake = target_lang in _SNAKE_TARGETS
    req: dict[str, list[str]] = {}

    for fpath in files:
        src_rel = fpath.relative_to(root).as_posix()
        out_rel = out_path_map.get(src_rel)
        if not out_rel:
            continue
        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        class_name = fpath.stem
        methods    = extractor(code, class_name)
        if not methods:
            continue

        # Apply naming convention to method names (Java → Python needs snake_case)
        if do_snake and source_lang not in ("python",):
            methods = [_to_snake_case(m) for m in methods]

        # Prepend constructor target name if source has one
        ctor = _CTOR_TARGET.get(target_lang)
        if ctor and ctor not in methods:
            has_ctor = (
                bool(re.search(r"def\s+__init__\s*\(", code))
                if source_lang == "python"
                else bool(re.search(rf"\b{re.escape(class_name)}\s*\(", code))
            )
            if has_ctor:
                methods = [ctor] + methods

        req[out_rel] = methods
    return req


def _build_source_naming(
    files: list[Path],
    root: Path,
    source_lang: str,
    schema: dict,
    target_lang: str,
) -> dict[str, str]:
    """
    Build naming map from source files for non-C/C++ languages.
    Returns {"ClassName.sourceMethod": "targetName"} for every public method.
    """
    extractor = _SOURCE_EXTRACTORS.get(source_lang)
    if not extractor:
        return {}

    do_snake = target_lang in _SNAKE_TARGETS
    naming: dict[str, str] = {}

    for fpath in files:
        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        class_name = fpath.stem

        # Constructor entry
        has_ctor = (
            bool(re.search(r"def\s+__init__\s*\(", code))
            if source_lang == "python"
            else bool(re.search(rf"\b{re.escape(class_name)}\s*\(", code))
        )
        if has_ctor:
            ctor = _CTOR_TARGET.get(target_lang, class_name)
            naming[f"{class_name}.{class_name}"] = ctor

        # Public methods
        for method in extractor(code, class_name):
            if source_lang == "python" and do_snake:
                target_name = method        # already snake_case
            elif do_snake:
                target_name = _to_snake_case(method)
            else:
                target_name = method
            naming[f"{class_name}.{method}"] = target_name

    # Field renames from schema
    for cls_name, cls_info in schema.get("classes", {}).items():
        for field in cls_info.get("protected_fields", []) + cls_info.get("fields", []):
            target_field = _to_snake_case(field) if do_snake else field
            if field != target_field:
                naming[f"{cls_name}.{field}"] = target_field

    return naming


def _make_inheritance_hint(class_name: str, parent: str, target_lang: str) -> str:
    """Return the correct class declaration line for a subclass in the target language."""
    if target_lang == "python":
        return f"class {class_name}({parent}):"
    elif target_lang in ("typescript", "javascript"):
        return f"class {class_name} extends {parent} {{"
    elif target_lang == "java":
        return f"class {class_name} extends {parent} {{"
    return ""


def _fix_callsite_casing(code: str, naming: dict[str, str], target_lang: str) -> str:
    """
    Deterministic post-process for main/entry-point files.
    Replaces camelCase method calls with their snake_case equivalents from the naming map.
    Only rewrites call sites (.methodName() patterns) — never touches identifiers elsewhere.
    """
    if not naming or target_lang not in _SNAKE_TARGETS:
        return code

    # Build a method-level rename table: {camelName: snake_name}
    # Keys in naming are "ClassName.cppMethod" — we only need the method part.
    renames: dict[str, str] = {}
    for src_sym, tgt_name in naming.items():
        src_method = src_sym.split(".", 1)[-1]
        # Only add if this is actually a rename (not a constructor/destructor)
        if src_method != tgt_name and src_method not in ("__init__", "__del__") \
                and not src_method.startswith("~") and tgt_name not in ("__init__", "__del__"):
            renames[src_method] = tgt_name

    for src_method, tgt_name in renames.items():
        # Only replace .camelMethod( — the leading dot ensures it's a method call
        code = re.sub(
            rf"(?<=\.){re.escape(src_method)}(?=\s*\()",
            tgt_name,
            code,
        )
    return code


def _fix_missing_inheritance(
    code: str,
    schema: dict,
    out_rel: str,
    target_lang: str,
) -> str:
    """
    Post-process: if schema says class Y extends X but the output has 'class Y:'
    (no parent declared), patch the class declaration to include the parent.
    Works for all source languages; patching syntax is target-language-aware.
    """
    stem = Path(out_rel).stem
    cls_info = schema.get("classes", {}).get(stem)
    if not cls_info:
        return code
    parent = cls_info.get("inherits")
    if not parent:
        return code

    if target_lang == "python":
        # class Foo: → class Foo(Parent):  only when no parent already declared
        patched = re.sub(
            rf"\bclass\s+{re.escape(stem)}\s*(?!\()\s*:",
            f"class {stem}({parent}):",
            code,
        )
    elif target_lang in ("javascript", "typescript"):
        patched = re.sub(
            rf"\bclass\s+{re.escape(stem)}\s*(?!extends)\s*\{{",
            f"class {stem} extends {parent} {{",
            code,
        )
    elif target_lang == "java":
        patched = re.sub(
            rf"\bclass\s+{re.escape(stem)}\s*(?!extends)\s*\{{",
            f"class {stem} extends {parent} {{",
            code,
        )
    else:
        patched = code

    return patched


def _make_abstract_hint(class_name: str, target_lang: str) -> str:
    """Return the correct abstract class declaration line for the target language."""
    if target_lang == "python":
        return f"class {class_name}(ABC):  # requires: from abc import ABC, abstractmethod"
    elif target_lang == "typescript":
        return f"abstract class {class_name} {{"
    elif target_lang == "javascript":
        return f"// Note: JavaScript has no native abstract — document with JSDoc @abstract"
    elif target_lang == "java":
        return f"public abstract class {class_name} {{"
    return ""


def _fix_import_paths(code: str, out_rel: str, target_lang: str) -> str:
    """
    Fix wrongly-prefixed import paths in files that live inside a subdirectory.
    E.g. LibrarySystem/Library.py importing from .LibrarySystem.Book
    should be from .Book (same directory, no parent prefix needed).
    Similarly LibrarySystem/Library.ts importing from "./LibrarySystem/Book"
    should be from "./Book".
    """
    out_dir  = Path(out_rel).parent
    dir_name = out_dir.name
    if not dir_name or str(out_dir) == ".":
        return code

    if target_lang == "python":
        # from .LibrarySystem.Book import X  →  from .Book import X
        code = re.sub(
            rf"\bfrom\s+\.{re.escape(dir_name)}\.(\w+)\s+import",
            r"from .\1 import",
            code,
        )
    elif target_lang in ("javascript", "typescript"):
        # "./LibrarySystem/Book" or './LibrarySystem/Book.js'  →  './Book' / './Book.js'
        def _rewrite(m: re.Match) -> str:
            q     = m.group(1)
            rest  = m.group(2)          # everything after "./"
            # strip leading dir_name/ prefix if present
            prefix = dir_name + "/"
            if rest.startswith(prefix):
                rest = rest[len(prefix):]
            return f"{q}./{rest}{q}"

        code = re.sub(
            r'(["\'])\./' + re.escape(dir_name) + r"/([^\"']+)\1",
            _rewrite,
            code,
        )
    return code


def _ensure_named_exports(code: str, target_lang: str) -> str:
    """
    JS/TS: every top-level class that isn't already exported gets
    `export` prepended to its class declaration.
    Also normalises `export default class Foo` → `export class Foo`
    so imports can uniformly use named-import syntax.
    """
    if target_lang not in ("javascript", "typescript"):
        return code

    # Normalise: export default class Foo → export class Foo
    code = re.sub(
        r"\bexport\s+default\s+((?:abstract\s+)?class\s+\w+)",
        r"export \1",
        code,
    )
    # Normalise: export default ClassName; (statement form)
    code = re.sub(r"\bexport\s+default\s+(\w+)\s*;", r"export { \1 };", code)

    # Add `export` to class declarations that are missing it
    top_level_classes = re.findall(
        r"^(?:abstract\s+)?class\s+(\w+)", code, re.MULTILINE
    )
    for name in top_level_classes:
        already = bool(
            re.search(rf"\bexport\s+(?:abstract\s+)?class\s+{re.escape(name)}\b", code)
            or re.search(rf"export\s*\{{[^}}]*\b{re.escape(name)}\b", code)
        )
        if not already:
            code = re.sub(
                rf"^((?:abstract\s+)?class\s+{re.escape(name)}\b)",
                r"export \1",
                code,
                count=1,
                flags=re.MULTILINE,
            )
    return code


def _fix_color_module_access(
    code: str,
    synth_symbols: dict[str, list[str]],
    target_lang: str,
) -> str:
    """
    Python only: when Colors/Color is a module-level constants file (not a class),
    replace Color.CONSTANT / Colors.CONSTANT with just CONSTANT.
    JS/TS/Java correctly use static class access, so this pass skips them.
    """
    if target_lang != "python":
        return code

    constants: list[str] = []
    for stem, syms in synth_symbols.items():
        if stem.lower() in ("colors", "color"):
            constants.extend(syms)
    if not constants:
        return code

    for const in constants:
        code = re.sub(rf"\bColors?\.{re.escape(const)}\b", const, code)
    return code


def _fix_python_fstring_ternaries(code: str, target_lang: str, filename: str) -> str:
    """
    Python only. Detects f-strings where a ternary expression sits inside the
    string literal rather than inside {} — it prints as literal text instead of
    evaluating. Runs a targeted single-file repair prompt when detected.

    Wrong:  f"Status: \\033[92mAvailable\\033[0m if self.is_available() else \\033[91mChecked Out\\033[0m"
    Right:  f"Status: {GREEN + 'Available' if self.is_available() else RED + 'Checked Out'}{RESET}"
    """
    if target_lang != "python":
        return code

    bug_lines: list[int] = []
    for lineno, line in enumerate(code.splitlines(), 1):
        # Must contain an f-string opener
        if not re.search(r'\bf["\']', line):
            continue
        if " if " not in line or " else " not in line:
            continue
        m = re.search(r'\bf["\']', line)
        if not m:
            continue
        if_pos = line.find(" if ", m.start())
        if if_pos == -1:
            continue
        # Count unbalanced { between f-string opener and ' if ':
        # if count == 0, the ' if ' is outside {} — unevaluated ternary
        segment     = line[m.start() : if_pos]
        open_count  = segment.count("{") - segment.count("}")
        if open_count == 0:
            bug_lines.append(lineno)

    if not bug_lines:
        return code

    bug_str = ", ".join(str(l) for l in bug_lines)
    prompt = (
        f"You are an expert Python developer fixing a specific bug in this file.\n\n"
        f"BUG on line(s) {bug_str}: the ternary expression is INSIDE the f-string literal "
        f"(not inside {{}}) so it prints as literal text instead of evaluating.\n\n"
        f"WRONG:  f\"text \\033[92mAvailable\\033[0m if self.is_available() else "
        f"\\033[91mChecked Out\\033[0m\"\n"
        f"RIGHT:  f\"text {{GREEN + 'Available' if self.is_available() else "
        f"RED + 'Checked Out'}}{{RESET}}\"\n\n"
        f"Rules:\n"
        f"- Fix ONLY the f-string ternary bug. Do not change any other logic.\n"
        f"- Wrap the ternary expression in {{}} so it evaluates at runtime.\n"
        f"- Preserve all imports, method names, and class structure exactly.\n"
        f"- Output the COMPLETE fixed Python file. No markdown fences. No explanation.\n\n"
        f"FILE ({filename}):\n{code[:10000]}\n\n"
        f"Fixed Python code:"
    )
    try:
        fixed = _strip_fences(_call_model(prompt, CONVERT_MODEL, timeout=120))
        if fixed.strip():
            return fixed
    except Exception:
        pass
    return code


def _contract_context_block(
    contract: dict,
    import_map: dict[str, list[str]],
    out_file: str,
    peer_callable: "dict[str, list[str]] | None" = None,
) -> str:
    """Format the translation contract as a bounded prompt block for one output file."""
    if not contract and not import_map and not peer_callable:
        return ""

    lines = [
        "TRANSLATION CONTRACT — these decisions are locked; every file uses them:"
    ]

    naming = contract.get("naming", {})
    if naming:
        lines.append("\nNAMING — use these EXACT target-language names for all cross-file calls:")
        for i, (src_sym, tgt_name) in enumerate(naming.items()):
            if i >= 80:
                lines.append(f"  … and {len(naming) - 80} more")
                break
            lines.append(f"  {src_sym} → {tgt_name}")

    abstract = contract.get("abstract_classes", [])
    concrete = contract.get("concrete_classes", [])
    if abstract:
        lines.append(f"\nABSTRACT (use abstract base class mechanism): {', '.join(abstract)}")
    if concrete:
        lines.append(f"CONCRETE (do NOT make abstract, no ABC): {', '.join(concrete)}")

    file_imports = import_map.get(out_file, [])
    if file_imports:
        lines.append("\nIMPORTS FOR THIS FILE — paste these EXACTLY at the top:")
        for stmt in file_imports:
            lines.append(f"  {stmt}")

    req      = contract.get("required_methods", {})
    file_req = req.get(out_file, [])
    if file_req:
        lines.append(
            "\nREQUIRED METHODS — every one MUST be fully implemented (not just declared):"
        )
        for m in file_req:
            lines.append(f"  - {m}")

    if peer_callable:
        lines.append(
            "\nPEER CALLABLE METHODS — you may ONLY call methods from this exact list "
            "on each peer object. Calling any other method causes AttributeError at runtime:"
        )
        for cls_name, methods in peer_callable.items():
            lines.append(f"  {cls_name}: {', '.join(methods)}")

    return "\n".join(lines)


def _is_stub_body(name: str, code: str, target_lang: str) -> bool:
    """Return True if the named method exists but has a stub/empty body."""
    if target_lang == "python":
        # Match: def name(...): <body until next def/class or EOF>
        m = re.search(
            rf"def\s+{re.escape(name)}\s*\([^)]*\)[^:]*:(.*?)(?=\n[ \t]*(?:def |class |\Z))",
            code, re.DOTALL,
        )
        if not m:
            return False
        # Exempt @abstractmethod — a pass body there is intentional
        pre = code[: m.start()]
        if re.search(r"@abstractmethod\s*$", pre.rstrip()):
            return False
        body_lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
        if not body_lines:
            return True
        stub_re = re.compile(
            r"^pass$|^#\s*(TODO|stub|implement|fixme|placeholder)",
            re.IGNORECASE,
        )
        return all(stub_re.match(bl) for bl in body_lines)
    else:
        # C++/Java: find MethodName( ... ) { body }  (single-brace depth)
        m = re.search(
            rf"\b{re.escape(name)}\s*\([^)]*\)[^{{;]*\{{([^{{}}]*)\}}",
            code,
        )
        if not m:
            return False
        body = m.group(1).strip()
        if not body:
            return True
        stub_re = re.compile(
            r"^(//\s*(TODO|stub|implement|fixme|placeholder)"
            r"|/\*\s*(stub|todo)\s*\*/"
            r"|return\s+(null|0|false|nullptr|None|\"\")\s*;"
            r"|return\s*;)$",
            re.IGNORECASE,
        )
        body_lines = [l.strip() for l in body.splitlines() if l.strip()]
        return bool(body_lines) and all(stub_re.match(bl) for bl in body_lines)


def _check_completeness(
    code: str,
    required: list[str],
    target_lang: str,
    required_enums: Optional[dict[str, list[str]]] = None,
) -> list[str]:
    """Return the subset of required method names not found (or only stubbed) in code,
    plus any enum values absent from the output."""
    missing = []
    for method in required:
        name = method.split("(")[0].strip()
        if not name:
            continue
        if target_lang == "python":
            pattern = rf"def\s+{re.escape(name)}\s*\("
        else:
            pattern = rf"\b{re.escape(name)}\s*[(\s{{]"
        if not re.search(pattern, code):
            missing.append(method)
        elif _is_stub_body(name, code, target_lang):
            missing.append(method)
    # Enum value completeness: every declared enum value must appear as an identifier
    if required_enums:
        for enum_fqn, values in required_enums.items():
            for val in values:
                if not re.search(rf"\b{re.escape(val)}\b", code):
                    missing.append(f"enum value: {enum_fqn}::{val}")
    return missing


def _complete_missing_methods(
    code: str,
    missing: list[str],
    source_code: str,
    source_lang: str,
    target_lang: str,
    contract_block: str,
) -> str:
    """Re-prompt the model to produce the full file with all missing methods included."""
    missing_str = "\n".join(f"  - {m}" for m in missing)
    prompt = (
        f"You are an expert {target_lang} developer completing a partially translated file.\n\n"
        f"This {target_lang} file is INCOMPLETE. It is missing these required methods:\n"
        f"{missing_str}\n\n"
        f"CURRENT {target_lang} FILE (incomplete):\n{code[:6000]}\n\n"
        f"ORIGINAL {source_lang} SOURCE (reference only):\n{source_code[:8000]}\n\n"
        f"{contract_block}\n\n"
        f"Output the COMPLETE {target_lang} file with ALL methods fully implemented — "
        f"both the ones already present AND all the missing ones listed above.\n"
        f"Output ONLY raw {target_lang} code. No markdown fences. No explanation."
    )
    try:
        result = _strip_fences(_call_model(prompt, CONVERT_MODEL, timeout=240))
        if result.strip():
            return result
    except Exception:
        pass
    return code


def _strip_fences(text: str) -> str:
    """Remove markdown code fences the model may have added."""
    text = text.strip()
    # Remove opening fence (``` or ```python etc.)
    text = re.sub(r'^```[a-zA-Z0-9]*\s*\n?', '', text)
    # Remove any trailing closing fence — handles stray ``` at end of file
    text = re.sub(r'\n?```+\s*$', '', text)
    return text.strip()


def _lang_rules(target_lang: str) -> str:
    rules: dict[str, str] = {
        "python": (
            "PYTHON RULES:\n"
            "- Ternary: `x if condition else y`  — NEVER `(condition) * x or y`\n"
            "- File errors: `except FileNotFoundError` — not bare `except` or `except IOError`\n"
            "- Private attrs: single underscore `_name` — not double\n"
            "- Abstract: `from abc import ABC, abstractmethod`\n"
            "- Input: built-in `input()` — no extra import needed\n"
        ),
        "typescript": (
            "TYPESCRIPT RULES:\n"
            "- User input: `import * as readline from 'readline-sync'` then `readline.question(...)`\n"
            "- Access: use `protected` (not `private`) for methods subclasses may override\n"
            "- Variables: `let` for mutable state — not `const`\n"
            "- Strings to numbers: `parseInt(s)` or `Number(s)`\n"
            "- File I/O: use `import * as fs from 'fs'` with `fs.readFileSync` / `fs.writeFileSync` — "
            "NEVER use FileReader, fetch, XMLHttpRequest, or any browser API. Node.js only.\n"
            "- Exports: every class MUST use `export class ClassName` or `export { ClassName }` — "
            "NEVER `export default ClassName`\n"
        ),
        "javascript": (
            "JAVASCRIPT RULES:\n"
            "- User input: `import readline from 'readline-sync'` then `readline.question(...)`\n"
            "- Variables: `let` for mutable state — not `const`\n"
            "- Strings to numbers: `parseInt(s)` or `Number(s)`\n"
            "- No type annotations — plain JS only\n"
            "- File I/O: use the built-in `fs` module (`import fs from 'fs'`) with "
            "`fs.readFileSync` / `fs.writeFileSync` — NEVER FileReader or browser APIs.\n"
            "- Exports: every class MUST use `export class ClassName` or end with "
            "`export { ClassName }` — NEVER `export default`\n"
        ),
        "java": (
            "JAVA RULES:\n"
            "- Scanner: declare as class field `private Scanner scanner = new Scanner(System.in);` — never close it\n"
            "- File errors: `catch (FileNotFoundException e)` — not bare `catch (Exception e)` for file I/O\n"
            "- Imports: ALWAYS add fully qualified stdlib imports for every class used — "
            "`import java.util.Scanner;`, `import java.util.ArrayList;`, `import java.util.List;`, "
            "`import java.io.IOException;`, `import java.io.BufferedReader;`, `import java.io.InputStreamReader;`, "
            "`import java.nio.file.Files;`, `import java.nio.file.Path;`, `import java.nio.file.Paths;`, "
            "`import java.nio.file.StandardOpenOption;`, `import java.net.http.HttpClient;`. NEVER `import Scanner;`\n"
            "- HTTP: use `java.net.http.HttpClient` (JDK 11+); use `System.getenv(\"KEY\")` for env vars — NOT Dotenv\n"
            "- Access: fields that subclasses access directly MUST be `protected`, not `private`\n"
            "- Abstract: if the source has pure virtual (abstract) methods, declare the class `abstract` "
            "and mark those methods `abstract`\n"
            "- No C functions: `srand()`, `rand()`, `printf()` do NOT exist in Java — "
            "use `Math.random()`, `new Random(seed)`, `System.out.println()` instead\n"
            "- Consistent naming: use the EXACT same class name in every file — never mix `Color` and `Colors`\n"
        ),
        "cpp": (
            "C++ RULES:\n"
            "- Header split: every class MUST have a matching .h header with #pragma once. "
            "The .cpp implements it; other files #include the .h. Always write #include \"ClassName.h\" "
            "for every project class you reference — NEVER assume a class is visible without it.\n"
            "- Entry point: program entry MUST be `int main()` — NEVER `Main::main()` or any class method.\n"
            "- String input with spaces: use `std::getline(std::cin, var)` — "
            "NEVER `std::cin >> var` for names or multi-word text (stops at whitespace).\n"
            "- Java String methods DO NOT EXIST on std::string:\n"
            "    equalsIgnoreCase → convert both to lowercase with std::transform then compare\n"
            "    contains(sub)    → str.find(sub) != std::string::npos\n"
            "    format/StringFormat → std::ostringstream with << operator — StringFormat() is fictional\n"
            "    isEmpty()        → str.empty()\n"
            "    trim()           → manual substr or boost::algorithm::trim\n"
            "- Formatted numbers: use std::ostringstream with std::setw/std::setfill, "
            "OR std::sprintf into a char buffer — NEVER static_cast<std::string>(intValue).\n"
            "- int/double to string: std::to_string(x) — NEVER static_cast<std::string>(x).\n"
            "- Exception specs: NEVER write `throw(ExceptionType)` — removed in C++17. "
            "Just omit the spec entirely.\n"
            "- printf newlines: use \\n in the format string — %n is a dangerous write-pointer specifier, NOT a newline.\n"
            "- Memory: use std::shared_ptr<T> for shared ownership, std::unique_ptr<T> for exclusive. "
            "NEVER raw `new` without a matching `delete` or smart pointer.\n"
            "- Casts: use static_cast<T>, dynamic_cast<T*> — NEVER C-style (T*)x.\n"
            "- Scope resolution: Colors::CYAN — NEVER Colors.CYAN (C++ uses :: not .).\n"
            "- Namespace: pick ONE namespace for the whole project and apply it consistently, "
            "OR use no namespace — NEVER mix files with and without namespace.\n"
            "- Includes: ALWAYS add all needed system headers:\n"
            "    <string> <vector> <map> <memory> <iostream> <fstream> <sstream>\n"
            "    <stdexcept> <algorithm> <filesystem> <iomanip> <regex> <functional>\n"
            "- Inheritance: override methods MUST match the base class signature exactly "
            "(same const-ness, same parameter types) — const mismatch makes it a new method, not an override.\n"
            # ── #9: silent-logic anti-patterns ─────────────────────────────────
            "- Zero-padding: Java String.format(\"%s%08d\", prefix, id) → "
            "  use std::ostringstream: oss << prefix << std::setw(8) << std::setfill('0') << id; return oss.str(); "
            "  NEVER to_string(id).substr(0,8) — that TRUNCATES, it does NOT pad.\n"
            "- Pipe-split deserialize: NEVER use >> on string fields that may contain spaces. "
            "  Always use std::getline(iss, field, '|') for EVERY field in pipe-delimited deserialization.\n"
            "- Enum serialization: NEVER cast enum to int in serialize() — e.g. static_cast<int>(type) "
            "  is wrong. Use an explicit string mapping: "
            "  if (type == Type::DEPOSIT) return \"DEPOSIT\"; if (type == Type::WITHDRAWAL) return \"WITHDRAWAL\"; etc.\n"
            # ── #12: structural C++ violations ─────────────────────────────────
            "- NEVER put #pragma once in a .cpp file — #pragma once belongs ONLY in .h headers.\n"
            "- NEVER define static const or const variables in a header file body — "
            "  use `inline const` (C++17) or move the definition to the .cpp. "
            "  Non-inline header-body definitions cause ODR violations across translation units.\n"
            "- A .cpp file MUST NOT redeclare a class body. #include the .h header and implement "
            "  methods as ClassName::methodName(...) { ... }. Declaring the class again in .cpp is always wrong.\n"
        ),
    }
    text = rules.get(target_lang, "")
    if not text:
        return ""
    return f"\n### {text}"


def _is_constants_header(code: str) -> bool:
    """True if .h file has constant definitions but no class/struct body."""
    has_constants = bool(
        re.search(r'#define\s+[A-Z_]\w*\s+\S', code) or
        re.search(r'^\s*(?:static\s+)?const\s+\w+\s+\w+\s*=', code, re.MULTILINE)
    )
    has_class = bool(re.search(r'\b(?:class|struct)\s+\w+\s*(?::\s*\w[\w\s,]*)?\{', code))
    return has_constants and not has_class


def _synth_constants_file(
    h_code: str, h_rel: str, target_lang: str
) -> Optional[tuple[str, str, list[str]]]:
    """
    Deterministically generate a constants file from a header-only .h file.
    Returns (output_filename, content, symbol_names) or None.
    """
    # Use [ \t]+ (horizontal whitespace) so the separator never spans lines,
    # and [^\n]+ so the value stops at the newline.
    # This prevents header guards like `#define COLORS_H` (no value) from
    # pulling in the next #define line as their "value".
    defines = re.findall(r'#define[ \t]+([A-Z_]\w*)[ \t]+([^\n]+)', h_code)
    consts  = re.findall(r'const\s+\w+\s+([A-Z_]\w*)\s*=\s*([^;]+);', h_code)
    all_c   = [(n, v.strip()) for n, v in defines if n and v.strip()] + \
              [(n, v.strip()) for n, v in consts if n and v.strip()]
    if not all_c:
        return None

    stem  = Path(h_rel).stem
    names = [n for n, _ in all_c]

    # Preserve the source directory so Colors.h in LibrarySystem/ → LibrarySystem/Colors.py.
    # This keeps the synthesized file co-located with the files that import it, making
    # relative imports correct (from .Colors import ...) rather than requiring (from ..Colors).
    h_dir = str(Path(h_rel).parent).replace("\\", "/")
    def _out(ext: str) -> str:
        return f"{h_dir}/{stem}{ext}" if h_dir and h_dir != "." else f"{stem}{ext}"

    if target_lang == "python":
        lines = [f"# Constants from {h_rel}"] + [f"{n} = {v}" for n, v in all_c]
        return _out(".py"), "\n".join(lines), names

    if target_lang == "javascript":
        lines = [f"// Constants from {h_rel}"] + [f"export const {n} = {v};" for n, v in all_c]
        return _out(".js"), "\n".join(lines), names

    if target_lang == "typescript":
        lines = [f"// Constants from {h_rel}"] + [f"export const {n} = {v};" for n, v in all_c]
        return _out(".ts"), "\n".join(lines), names

    if target_lang == "java":
        def _java_const_type(v: str) -> str:
            s = v.strip()
            if s.startswith('"') or '"' in s:
                return "String"
            try:
                int(s, 0)
                return "int"
            except ValueError:
                pass
            try:
                float(s.rstrip("fFdDlL"))
                return "double"
            except ValueError:
                pass
            return "String"
        body  = [f"    public static final {_java_const_type(v)} {n} = {v};" for n, v in all_c]
        lines = [f"// Constants from {h_rel}", f"public class {stem} {{"] + body + ["}"]
        return _out(".java"), "\n".join(lines), names

    return None


def _strip_redefined_classes(
    main_code: str,
    peer_stems: dict[str, list[str]],
    target_lang: str,
) -> str:
    """
    After LLM fixes main, deterministically strip any inline class definitions
    whose names already exist in peer modules. Prepend the correct import instead.
    """
    peer_class_map: dict[str, tuple[str, list[str]]] = {}
    for stem, syms in peer_stems.items():
        for sym in syms:
            peer_class_map[sym] = (stem, syms)

    if not peer_class_map:
        return main_code

    lines = main_code.splitlines()
    result_lines: list[str] = []
    imports_to_add: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        class_name: Optional[str] = None

        if target_lang == "python":
            m = re.match(r'^class\s+(\w+)', line)
            if m:
                class_name = m.group(1)
        elif target_lang in ("javascript", "typescript"):
            m = re.match(r'^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)', line)
            if m:
                class_name = m.group(1)
        elif target_lang == "java":
            m = re.match(r'^(?:public\s+)?(?:abstract\s+)?class\s+(\w+)', line)
            if m:
                class_name = m.group(1)

        if class_name and class_name in peer_class_map:
            stem, syms = peer_class_map[class_name]
            imp = _import_statement(stem, syms, target_lang)
            if imp not in imports_to_add:
                imports_to_add.append(imp)

            if target_lang == "python":
                i += 1
                while i < len(lines):
                    if lines[i].strip() == "" or lines[i][:1] in (" ", "\t"):
                        i += 1
                    else:
                        break
            else:
                depth = line.count("{") - line.count("}")
                opened = depth > 0
                i += 1
                while i < len(lines):
                    d = lines[i].count("{") - lines[i].count("}")
                    depth += d
                    i += 1
                    if d > 0:
                        opened = True
                    if opened and depth <= 0:
                        break
            continue

        result_lines.append(line)
        i += 1

    if imports_to_add:
        return "\n".join(imports_to_add) + "\n" + "\n".join(result_lines)
    return "\n".join(result_lines)


def _sanitize_java_imports(code: str) -> str:
    """Strip bare Java imports with no package path (e.g. `import Scanner;`)."""
    return "\n".join(
        line for line in code.splitlines()
        if not re.match(r'^\s*import\s+[A-Z][a-zA-Z]*\s*;', line)
    )


# Mapping of code tokens → required import statements for Java stdlib
_JAVA_IMPORT_TRIGGERS: list[tuple[str, str]] = [
    ("Scanner",              "import java.util.Scanner;"),
    ("ArrayList<",           "import java.util.ArrayList;"),
    ("List<",                "import java.util.List;"),
    ("Map<",                 "import java.util.Map;"),
    ("HashMap<",             "import java.util.HashMap;"),
    ("Arrays.",              "import java.util.Arrays;"),
    ("Collections.",         "import java.util.Collections;"),
    ("Collectors.",          "import java.util.stream.Collectors;"),
    ("IOException",          "import java.io.IOException;"),
    ("FileNotFoundException","import java.io.FileNotFoundException;"),
    ("FileWriter",           "import java.io.FileWriter;"),
    ("BufferedReader",       "import java.io.BufferedReader;"),
    ("BufferedWriter",       "import java.io.BufferedWriter;"),
    ("InputStreamReader",    "import java.io.InputStreamReader;"),
    ("PrintWriter",          "import java.io.PrintWriter;"),
    ("Files.",               "import java.nio.file.Files;"),
    ("Paths.",               "import java.nio.file.Paths;"),
    ("Path ",                "import java.nio.file.Path;"),
    ("StandardOpenOption",   "import java.nio.file.StandardOpenOption;"),
    ("HttpClient",           "import java.net.http.HttpClient;"),
    ("HttpRequest",          "import java.net.http.HttpRequest;"),
    ("HttpResponse",         "import java.net.http.HttpResponse;"),
    ("URI.create(",          "import java.net.URI;"),
    ("new Random(",          "import java.util.Random;"),
    ("Optional<",            "import java.util.Optional;"),
]


def _inject_java_imports(code: str) -> str:
    """Deterministically inject missing stdlib imports into a Java file."""
    lines = code.splitlines()
    existing = {line.strip() for line in lines if line.strip().startswith("import ")}

    # Insert after the last existing import or package declaration
    insert_at = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("import ") or s.startswith("package "):
            insert_at = i + 1

    to_add = [
        stmt for trigger, stmt in _JAVA_IMPORT_TRIGGERS
        if stmt not in existing and trigger in code
    ]

    if not to_add:
        return code
    return "\n".join(lines[:insert_at] + to_add + lines[insert_at:])


# Mapping of code tokens → required #include directives for C++ stdlib
_CPP_INCLUDE_TRIGGERS: list[tuple[str, str]] = [
    ("std::string",           "#include <string>"),
    ("std::vector",           "#include <vector>"),
    ("std::map",              "#include <map>"),
    ("std::unordered_map",    "#include <unordered_map>"),
    ("std::shared_ptr",       "#include <memory>"),
    ("std::unique_ptr",       "#include <memory>"),
    ("std::make_shared",      "#include <memory>"),
    ("std::make_unique",      "#include <memory>"),
    ("std::cout",             "#include <iostream>"),
    ("std::cin",              "#include <iostream>"),
    ("std::cerr",             "#include <iostream>"),
    ("std::endl",             "#include <iostream>"),
    ("std::getline",          "#include <iostream>"),
    ("std::ifstream",         "#include <fstream>"),
    ("std::ofstream",         "#include <fstream>"),
    ("std::fstream",          "#include <fstream>"),
    ("std::ostringstream",    "#include <sstream>"),
    ("std::istringstream",    "#include <sstream>"),
    ("std::stringstream",     "#include <sstream>"),
    ("std::runtime_error",    "#include <stdexcept>"),
    ("std::invalid_argument", "#include <stdexcept>"),
    ("std::out_of_range",     "#include <stdexcept>"),
    ("std::exception",        "#include <stdexcept>"),
    ("std::sort",             "#include <algorithm>"),
    ("std::find",             "#include <algorithm>"),
    ("std::transform",        "#include <algorithm>"),
    ("std::filesystem",       "#include <filesystem>"),
    ("std::setw",             "#include <iomanip>"),
    ("std::setfill",          "#include <iomanip>"),
    ("std::setprecision",     "#include <iomanip>"),
    ("std::regex",            "#include <regex>"),
    ("std::function",         "#include <functional>"),
    ("std::to_string",        "#include <string>"),
    ("std::stoi",             "#include <string>"),
    ("std::stof",             "#include <string>"),
    ("std::stod",             "#include <string>"),
    ("std::list",             "#include <list>"),
    ("std::set",              "#include <set>"),
    ("std::pair",             "#include <utility>"),
]


def _inject_cpp_includes(code: str) -> str:
    """Deterministically inject missing stdlib #include directives into a C++ file."""
    lines = code.splitlines()
    existing = {line.strip() for line in lines if line.strip().startswith("#include")}

    # Insert after the last existing #include / #pragma line
    insert_at = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#include") or s.startswith("#pragma"):
            insert_at = i + 1

    to_add = [
        stmt for trigger, stmt in _CPP_INCLUDE_TRIGGERS
        if stmt not in existing and trigger in code
    ]

    if not to_add:
        return code
    return "\n".join(lines[:insert_at] + to_add + lines[insert_at:])


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


# ── Signature-based memory extraction ────────────────────────────────────────

def _sigs_python(code: str, body_lines: int) -> str:
    """Extract class/field/method signatures from Python code with body preview."""
    lines = code.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # Class declaration
        if re.match(r'^class\s+\w+', line):
            out.append(line)
            i += 1
            continue
        # Method definition — emit signature then preview body_lines lines
        m = re.match(r'^(\s*)def\s+\w+', line)
        if m:
            out.append(line)
            base_indent = len(m.group(1))
            j, count = i + 1, 0
            while j < len(lines) and count < body_lines:
                bl = lines[j]
                bs = bl.strip()
                if not bs or bs.startswith('#'):
                    j += 1
                    continue
                curr_indent = len(bl) - len(bl.lstrip())
                if curr_indent <= base_indent:
                    break
                out.append(' ' * (base_indent + 4) + bs[:100])
                count += 1
                j += 1
            if count >= body_lines:
                out.append(' ' * (base_indent + 4) + '...')
            # Skip past the full method body so we don't re-process its lines
            i = j
            continue
        i += 1
    return '\n'.join(out)


def _sigs_ts_js(code: str, body_lines: int) -> str:
    """Extract class/field/method signatures from TypeScript/JavaScript code with body preview."""
    _SKIP = {
        'if', 'for', 'while', 'switch', 'return', 'const', 'let', 'var',
        'import', 'export', 'new', 'super', 'this', 'try', 'catch', 'throw',
        'typeof', 'instanceof', 'else',
    }
    lines = code.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('*'):
            i += 1
            continue
        # Class declaration
        if re.match(r'^(?:export\s+)?(?:abstract\s+)?class\s+\w+', line):
            out.append(line.rstrip()[:140])
            i += 1
            continue
        # Typed field declaration (e.g. protected books: Book[] = [])
        if re.match(
            r'^\s+(?:(?:private|protected|public|readonly|static|declare)\s+)+\w+[?!]?\s*[=:;]',
            line,
        ):
            out.append(line.rstrip()[:120])
            i += 1
            continue
        # Method / constructor signature
        m = re.match(
            r'^(\s+)(?:(?:public|private|protected|static|async|abstract|override|readonly)\s+)*(\w+)\s*[(<]',
            line,
        )
        if m and m.group(2) not in _SKIP:
            out.append(line.rstrip()[:140])
            depth = line.count('{') - line.count('}')
            j = i + 1
            # Advance to opening brace if not on the same line
            while j < len(lines) and depth <= 0:
                depth += lines[j].count('{') - lines[j].count('}')
                j += 1
            count = 0
            while j < len(lines) and count < body_lines and depth > 0:
                bl = lines[j]
                bs = bl.strip()
                depth += bl.count('{') - bl.count('}')
                if depth <= 0:
                    break
                if bs and not bs.startswith('//'):
                    out.append('  ' + bs[:100])
                    count += 1
                j += 1
            if count >= body_lines:
                out.append('  ...')
        i += 1
    return '\n'.join(out)


def _sigs_java(code: str, body_lines: int) -> str:
    """Extract class/field/method signatures from Java code with body preview."""
    _SKIP = {
        'if', 'for', 'while', 'switch', 'return', 'new', 'catch', 'try',
        'throw', 'else', 'assert', 'case', 'default', 'break', 'continue',
    }
    lines = code.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith('//')
            or stripped.startswith('*')
            or stripped.startswith('import ')
            or stripped.startswith('package ')
        ):
            i += 1
            continue
        # Class declaration
        if re.match(r'^(?:public\s+)?(?:abstract\s+)?class\s+\w+', line):
            out.append(line.rstrip()[:140])
            i += 1
            continue
        # Field declaration (ends with ; and has no open paren before the semicolon)
        if (
            re.match(r'^\s+(?:private|protected|public)\s+', line)
            and ';' in line
            and '(' not in line.split(';')[0]
        ):
            out.append(line.rstrip()[:120])
            i += 1
            continue
        # Method / constructor signature
        m = re.match(
            r'^\s+(?:(?:public|private|protected|static|abstract|final|synchronized)\s+)*'
            r'(?:<[^>]+>\s+)?(?:[\w<>\[\]]+\s+)+(\w+)\s*\(',
            line,
        )
        if m and m.group(1) not in _SKIP:
            out.append(line.rstrip()[:140])
            depth = line.count('{') - line.count('}')
            j = i + 1
            while j < len(lines) and depth <= 0:
                depth += lines[j].count('{') - lines[j].count('}')
                j += 1
            count = 0
            while j < len(lines) and count < body_lines and depth > 0:
                bl = lines[j]
                bs = bl.strip()
                depth += bl.count('{') - bl.count('}')
                if depth <= 0:
                    break
                if bs and not bs.startswith('//'):
                    out.append('    ' + bs[:100])
                    count += 1
                j += 1
            if count >= body_lines:
                out.append('    ...')
        i += 1
    return '\n'.join(out)


def _sigs_cpp(code: str, body_lines: int) -> str:
    """Extract class/field/method signatures from C++ .h or .cpp code with body preview."""
    _SKIP = {
        'if', 'for', 'while', 'switch', 'return', 'new', 'catch', 'try',
        'throw', 'else', 'assert', 'break', 'continue', 'delete', 'namespace',
        'case', 'default',
    }
    lines = code.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Skip blanks, comments, preprocessor, using/namespace
        if (
            not stripped
            or stripped.startswith('//')
            or stripped.startswith('*')
            or stripped.startswith('#')
            or stripped.startswith('using ')
            or re.match(r'^namespace\s', stripped)
        ):
            i += 1
            continue
        # Class / struct declaration
        if re.match(r'^(?:class|struct)\s+\w+', stripped):
            out.append(line.rstrip()[:140])
            i += 1
            continue
        # Field declaration: type name_; (ends with ; no open paren)
        if (
            re.match(r'^\s+', line)
            and ';' in line
            and '(' not in line.split(';')[0]
            and re.search(r'\w+\s+\w+_?\s*;', line)
        ):
            out.append(line.rstrip()[:120])
            i += 1
            continue
        # Method definition: ReturnType [ClassName::]methodName(
        m = re.match(
            r'^(?:(?:virtual|static|explicit|inline|const|override)\s+)*'
            r'(?:[\w:<>*&~]+\s+)+'
            r'(?:\w+::)?(\w+)\s*\(',
            stripped,
        )
        if m and m.group(1) not in _SKIP:
            out.append(line.rstrip()[:140])
            # Walk into the body
            depth = line.count('{') - line.count('}')
            j = i + 1
            # Advance until we enter the opening brace
            while j < len(lines) and depth <= 0:
                depth += lines[j].count('{') - lines[j].count('}')
                j += 1
            count = 0
            while j < len(lines) and count < body_lines and depth > 0:
                bl = lines[j]
                bs = bl.strip()
                depth += bl.count('{') - bl.count('}')
                if depth <= 0:
                    break
                if bs and not bs.startswith('//'):
                    out.append('    ' + bs[:100])
                    count += 1
                j += 1
            if count >= body_lines:
                out.append('    ...')
        i += 1
    return '\n'.join(out)


def _extract_file_signatures(code: str, language: str, body_lines: int = 4) -> str:
    """
    Compact signature-based summary of a converted file.
    Shows class declarations, field assignments, and every method signature
    with `body_lines` preview lines from each body. Reveals data formats
    (save/load), constructor args, and return structures — far more useful
    for cross-file coordination than a raw line slice.
    """
    if language == "python":
        return _sigs_python(code, body_lines)
    if language in ("typescript", "javascript"):
        return _sigs_ts_js(code, body_lines)
    if language == "java":
        return _sigs_java(code, body_lines)
    if language == "cpp":
        return _sigs_cpp(code, body_lines)
    # unknown — fallback to first 80 lines
    return "\n".join(code.splitlines()[:80])


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
    # Only look at import lines — checking all text causes false positives
    # (e.g. `class Player(Entity):` would make us think Entity is already imported).
    import_lines = "\n".join(
        line for line in converted_code.splitlines()[:30]
        if re.match(r'\s*(?:import|from)\s', line)
    ).lower()
    to_add = []

    for stem, syms in sorted(peer_output_stems.items()):
        if not syms:
            continue
        name = stem.rsplit("/", 1)[-1]

        # Symbol referenced in source?
        if not any(re.search(r'\b' + re.escape(sym) + r'\b', source_code) for sym in syms):
            continue

        # Already imported? Check that the module name appears in an actual import line.
        if name.lower() in import_lines:
            continue

        to_add.append(_import_statement(stem, syms, target_lang))

    if not to_add:
        return converted_code
    return "\n".join(to_add) + "\n" + converted_code


def _reasoning_prepass(
    source_code: str,
    source_lang: str,
    target_lang: str,
    peer_signatures: str,
    contract_block: str,
    filename: str,
) -> str:
    """
    Mechanical cross-reference extraction for complex files (2+ deps or main).
    Asks the model to READ and COPY exact method names, constructor signatures,
    and persistence formats from the peer interfaces — no planning, no guessing.
    The result is injected AFTER the peer signatures in the generation prompt
    as a concrete lookup table, reinforcing what the model already read.
    """
    if not peer_signatures.strip():
        return ""

    prompt = (
        f"You are a code cross-reference extractor. Read the peer interfaces below.\n"
        f"Extract ONLY facts directly visible in the interfaces — do NOT guess or invent.\n\n"
        f"PEER MODULE INTERFACES:\n{peer_signatures[:5000]}\n\n"
        f"SOURCE FILE ({filename}) — the file that will USE these peers:\n{source_code[:2000]}\n\n"
        f"List ONLY what you can directly read from the peer interfaces above:\n"
        f"1. Every peer method this file calls — write as ClassName.methodName(args) "
        f"   using the EXACT names from the interfaces, no paraphrasing\n"
        f"2. Every peer constructor this file uses — write as ClassName(arg1, arg2, ...)\n"
        f"3. If any peer has save/load methods: copy the EXACT format lines "
        f"   (data separators, field order) from those method bodies\n\n"
        f"One entry per line. No prose. No code. Only names you can see above."
    )
    try:
        result = _call_model(prompt, CONVERT_MODEL, timeout=60)
        if result.strip():
            return result.strip()[:1200]
    except Exception:
        pass
    return ""


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
        preview = "\n".join(code.splitlines()[:100])
        sig_parts.append(f"// --- {out_path} ---\n{preview}")

    if len(map_lines) <= 1:
        return main_code

    # Detect whether any peer module exposes a save method
    save_method = "save_data" if target_lang == "python" else "saveData"
    has_save    = any(
        re.search(rf"\bdef\s+{save_method}\b|\b{save_method}\s*\(", c)
        for c in peer_converted.values()
    )
    save_rule = (
        f"5. The exit branch of the main loop MUST call the save method "
        f"(`{save_method}()`) on the library/manager object BEFORE the break/exit. "
        f"This preserves data between sessions.\n"
        if has_save else ""
    )

    prompt = (
        f"You are an expert {target_lang} developer fixing the main entry-point file of a converted codebase.\n"
        f"All module files have already been correctly converted — your job is to wire them together correctly.\n\n"
        f"{chr(10).join(map_lines)}\n\n"
        f"CONVERTED MODULE SIGNATURES (first 100 lines each):\n"
        f"{chr(10).join(sig_parts[:6])}\n\n"
        f"CURRENT main file:\n"
        f"```{target_lang}\n{main_code[:8000]}\n```\n\n"
        f"STRICT RULES — every rule is mandatory:\n"
        f"1. Replace every inline class body that duplicates a module in the list above "
        f"   with the correct import statement instead.\n"
        f"2. Do NOT define any class inline — IMPORT them from the files listed above.\n"
        f"3. Preserve all main() / game loop / menu logic and keep it working.\n"
        f"4. Align ALL method call-sites to use the EXACT method names shown in the module "
        f"   signatures above — NEVER invent method names or use wrong casing.\n"
        f"{save_rule}"
        f"{'6' if has_save else '5'}. Output ONLY the complete fixed {target_lang} file. No fences. No explanation."
    )

    try:
        out = _call_model(prompt, CONVERT_MODEL)
        return _strip_fences(out)
    except Exception:
        return main_code


# Persistence method stubs: (call_pattern, def_pattern, stub_code) per language.
# Injected when a method is called (e.g. self.load_data()) but never defined.
_PERSISTENCE_STUBS: dict[str, list[tuple[str, str, str]]] = {
    "python": [
        (r"\bself\.load_data\s*\(", r"^\s+def\s+load_data\b",
         "    def load_data(self):\n        pass\n"),
        (r"\bself\.save_data\s*\(", r"^\s+def\s+save_data\b",
         "    def save_data(self):\n        pass\n"),
    ],
    "typescript": [
        (r"\bthis\.loadData\s*\(", r"\bloadData\s*\(",
         "    loadData(): void {}\n"),
        (r"\bthis\.saveData\s*\(", r"\bsaveData\s*\(",
         "    saveData(): void {}\n"),
    ],
    "javascript": [
        (r"\bthis\.loadData\s*\(", r"\bloadData\s*\(",
         "    loadData() {}\n"),
        (r"\bthis\.saveData\s*\(", r"\bsaveData\s*\(",
         "    saveData() {}\n"),
    ],
    "java": [
        (r"\bloadData\s*\(", r"\bvoid\s+loadData\b",
         "    public void loadData() { /* stub */ }\n"),
        (r"\bsaveData\s*\(", r"\bvoid\s+saveData\b",
         "    public void saveData() { /* stub */ }\n"),
    ],
}


def _inject_persistence_stubs(code: str, target_lang: str) -> str:
    """
    Safety net: if a persistence method is called in the code (e.g.
    self.load_data() in __init__) but never defined, inject a minimal
    non-crashing stub so the program doesn't AttributeError on startup.
    The completeness check + repair should normally handle this; this is
    the last-resort fallback if that repair also failed.
    """
    for call_pat, def_pat, stub in _PERSISTENCE_STUBS.get(target_lang, []):
        called  = bool(re.search(call_pat, code, re.MULTILINE))
        defined = bool(re.search(def_pat,  code, re.MULTILINE))
        if called and not defined:
            if target_lang == "python":
                code = code.rstrip() + "\n\n" + stub
            else:
                last_brace = code.rfind("\n}")
                code = (
                    code[:last_brace] + "\n" + stub + code[last_brace:]
                    if last_brace != -1
                    else code.rstrip() + "\n" + stub
                )
    return code


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

    # peer_stems_no_main used in strip pass for ALL files + main
    peer_stems_no_main = {s: v for s, v in out_stem_syms.items() if not _IS_MAIN(s)}

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

        if src_code:
            peer_stems = {s: v for s, v in out_stem_syms.items()
                          if s.lower() != stem.lower() and not _IS_MAIN(s)}
            code = _inject_project_imports(code, src_code, target_lang, peer_stems)

        # Strip any class body the model copied from a peer module into this file
        code = _strip_redefined_classes(
            code,
            {s: v for s, v in peer_stems_no_main.items() if s != stem},
            target_lang,
        )

        # Fix wrongly-prefixed import paths (e.g. ./LibrarySystem/Book → ./Book)
        code = _fix_import_paths(code, out_path, target_lang)

        # Ensure every class is exported with a named export (JS/TS)
        code = _ensure_named_exports(code, target_lang)

        fixed[out_path] = code

    # Step 2: LLM fix for main + deterministic post-passes
    if main_key:
        peers = {p: fixed[p] for p in fixed if p != main_key}
        fixed[main_key] = _fix_main_llm(fixed[main_key], peers, target_lang)
        fixed[main_key] = _strip_redefined_classes(
            fixed[main_key], peer_stems_no_main, target_lang
        )
        fixed[main_key] = _fix_import_paths(fixed[main_key], main_key, target_lang)
        fixed[main_key] = _ensure_named_exports(fixed[main_key], target_lang)

    return fixed


# ── Layer 3: Formatter ────────────────────────────────────────────────────────

# Resolve project-local node_modules/.bin so tsc/prettier are found even when
# not installed globally.
_NODE_BINS = Path(__file__).parent.parent / "node_modules" / ".bin"

# Well-known fallback paths for compilers/tools on Windows (scoop, JDK).
_WIN_FALLBACK_BINS = [
    Path.home() / "scoop" / "apps" / "gcc" / "current" / "bin",
    Path.home() / "scoop" / "shims",
    Path("C:/Program Files/Microsoft") / f"jdk-17.0.19.10-hotspot" / "bin",
]

def _node_tool(name: str) -> Optional[str]:
    """Return path to a node tool: prefer global, fall back to project node_modules."""
    found = shutil.which(name)
    if found:
        return found
    suffix = ".cmd" if sys.platform == "win32" else ""
    local = _NODE_BINS / (name + suffix)
    return str(local) if local.exists() else None


def _system_tool(name: str) -> Optional[str]:
    """Return path to a system tool: prefer PATH, fall back to known install dirs."""
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if sys.platform == "win32" else "")
    for d in _WIN_FALLBACK_BINS:
        p = d / exe
        if p.exists():
            return str(p)
    return None


def _python_pkg_available(pkg: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(pkg) is not None


def _run(
    args: list,
    *,
    stdin_text: Optional[str] = None,
    timeout: int = 30,
    cwd: Optional[str] = None,
) -> "subprocess.CompletedProcess[str]":
    kw: dict = dict(capture_output=True, text=True, timeout=timeout)
    if stdin_text is not None:
        kw["input"] = stdin_text
    if cwd is not None:
        kw["cwd"] = cwd
    # .cmd/.bat scripts (npm-installed tools on Windows) need shell=True
    if sys.platform == "win32" and str(args[0]).lower().endswith((".cmd", ".bat")):
        cmd = " ".join(f'"{a}"' if " " in str(a) else str(a) for a in args)
        return subprocess.run(cmd, shell=True, **kw)
    return subprocess.run([str(a) for a in args], **kw)


def _format_code(code: str, filename: str, target_lang: str) -> str:
    """Layer 3: Run the language formatter via stdin. Returns formatted code or original."""
    try:
        if target_lang == "python" and _python_pkg_available("black"):
            r = _run([sys.executable, "-m", "black", "--quiet", "-"],
                     stdin_text=code, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout

        elif target_lang in ("typescript", "javascript"):
            prettier = _node_tool("prettier")
            if prettier:
                r = _run([prettier, "--stdin-filepath", filename],
                         stdin_text=code, timeout=30)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout

        elif target_lang == "java":
            prettier = _node_tool("prettier")
            plugin = _NODE_BINS.parent / "prettier-plugin-java" / "dist" / "index.mjs"
            if prettier and plugin.exists():
                r = _run([prettier, "--stdin-filepath", filename, "--plugin", str(plugin)],
                         stdin_text=code, timeout=30)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout

        elif target_lang == "cpp":
            clang_fmt = _node_tool("clang-format") or shutil.which("clang-format")
            if clang_fmt:
                r = _run([clang_fmt, "--assume-filename", filename],
                         stdin_text=code, timeout=30)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout

    except Exception:
        pass
    return code


# ── Layer 2: Compile check ────────────────────────────────────────────────────

def _compile_check(
    tmp_dir: Path, results: dict[str, str], target_lang: str
) -> dict[str, list[str]]:
    """
    Run the appropriate compiler/linter against all output files.
    Returns {filename: [error lines]}. Empty dict means all clean (or toolchain absent).
    """
    filenames = [f for f in results if not f.endswith(("tsconfig.json", "package.json"))]
    errors: dict[str, list[str]] = {}
    try:
        if target_lang == "python":
            if _python_pkg_available("pyflakes"):
                r = _run(
                    [sys.executable, "-m", "pyflakes"] + [str(tmp_dir / f) for f in filenames],
                    timeout=30,
                )
                for line in (r.stdout + r.stderr).splitlines():
                    norm = line.replace("\\", "/")
                    for fname in filenames:
                        if fname in norm or str(tmp_dir / fname).replace("\\", "/") in norm:
                            errors.setdefault(fname, []).append(line)
            else:
                import py_compile
                for fname in filenames:
                    try:
                        py_compile.compile(str(tmp_dir / fname), doraise=True)
                    except py_compile.PyCompileError as e:
                        errors[fname] = [str(e)]

        elif target_lang == "java":
            javac = _system_tool("javac")
            if javac:
                r = _run([javac] + [str(tmp_dir / f) for f in filenames], timeout=60)
                for line in (r.stdout + r.stderr).splitlines():
                    norm = line.replace("\\", "/")
                    for fname in filenames:
                        if fname in norm:
                            errors.setdefault(fname, []).append(line)

        elif target_lang == "typescript":
            tsc = _node_tool("tsc")
            if tsc:
                tsconfig = tmp_dir / "tsconfig.json"
                tsconfig.write_text(json.dumps({
                    "compilerOptions": {
                        "target": "ES2020", "module": "commonjs",
                        "strict": False, "noEmit": True,
                        "esModuleInterop": True, "skipLibCheck": True,
                    },
                    "include": ["*.ts"],
                }))
                r = _run([tsc, "--noEmit", "--project", str(tsconfig)],
                         timeout=60, cwd=str(tmp_dir))
                for line in (r.stdout + r.stderr).splitlines():
                    norm = line.replace("\\", "/")
                    for fname in filenames:
                        if fname in norm:
                            errors.setdefault(fname, []).append(line)

        elif target_lang == "javascript":
            node = shutil.which("node")
            if node:
                for fname in filenames:
                    r = _run([node, "--check", str(tmp_dir / fname)], timeout=15)
                    if r.returncode != 0:
                        errs = (r.stderr or r.stdout).splitlines()
                        if errs:
                            errors[fname] = errs

        elif target_lang == "cpp":
            cxx = _system_tool("g++") or _system_tool("clang++") or shutil.which("cl")
            if cxx:
                is_msvc = Path(cxx).name.lower().startswith("cl")
                # Write stub headers for any #include "X.h" that isn't present
                for fname in filenames:
                    if fname.endswith(".cpp"):
                        stub = tmp_dir / fname.replace(".cpp", ".h")
                        if not stub.exists():
                            stub.write_text("#pragma once\n")
                for fname in [f for f in filenames if f.endswith(".cpp")]:
                    if is_msvc:
                        flags = [cxx, "/Zs", "/TP", f"/I{tmp_dir}", str(tmp_dir / fname)]
                    else:
                        flags = [cxx, "-fsyntax-only", "-std=c++17",
                                 f"-I{tmp_dir}", str(tmp_dir / fname)]
                    r = _run(flags, timeout=30)
                    if r.returncode != 0:
                        errs = [
                            l for l in (r.stderr or r.stdout).splitlines()
                            if "No such file or directory" not in l
                            and "cannot open source file" not in l
                        ]
                        if errs:
                            errors[fname] = errs

    except Exception:
        pass
    return errors


# ── Layer 2: Repair ───────────────────────────────────────────────────────────

def _repair_file(
    code: str, errors: list[str], target_lang: str, filename: str
) -> str:
    """Ask the model to fix compilation errors. Returns repaired code or original on failure."""
    error_text = "\n".join(errors[:20])
    prompt = (
        f"You are an expert {target_lang} developer fixing compilation errors in a translated file.\n\n"
        f"The following {target_lang} file has compilation errors.\n"
        f"Fix ONLY the listed errors — do NOT change any logic, algorithms, or method names.\n"
        f"Output ONLY the corrected {target_lang} code with no markdown fences, no explanations.\n"
        f"\nFILE: {filename}\n"
        f"ERRORS:\n{error_text}\n"
        f"\n```{target_lang}\n{code[:8000]}\n```\n"
        f"\nFixed {target_lang} code:"
    )
    try:
        fixed = _strip_fences(_call_model(prompt, CONVERT_MODEL, timeout=120))
        return fixed if fixed.strip() else code
    except Exception:
        return code


# ── Postprocess orchestrator ──────────────────────────────────────────────────

def _postprocess(
    results: dict[str, str],
    target_lang: str,
    on_progress: Optional[Callable[[str, str, int, int], None]] = None,
) -> dict[str, str]:
    """
    Layer 3: format every output file.
    Layer 2: compile-check the whole project, repair files with errors,
             up to MAX_REPAIR_ATTEMPTS. No-ops gracefully if toolchain is absent.
    """
    base_total = len(results)

    # Layer 3 — formatter
    if on_progress:
        on_progress("(formatting…)", "converting", base_total + 2, base_total)
    current = {fname: _format_code(code, fname, target_lang) for fname, code in results.items()}

    # Java: inject missing stdlib imports before the first compile check
    if target_lang == "java":
        current = {
            k: (_inject_java_imports(v) if k.endswith(".java") else v)
            for k, v in current.items()
        }

    # Layer 2 — compile check + repair
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for fname, code in current.items():
            out = tmp_dir / fname
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(code, encoding="utf-8")

        for attempt in range(MAX_REPAIR_ATTEMPTS):
            label = "(checking…)" if attempt == 0 else f"(repairing… pass {attempt})"
            if on_progress:
                on_progress(label, "converting", base_total + 2, base_total + 1)

            errors_by_file = _compile_check(tmp_dir, current, target_lang)
            if not errors_by_file:
                break

            for fname, errs in errors_by_file.items():
                if fname not in current:
                    continue
                repaired = _repair_file(current[fname], errs, target_lang, fname)
                repaired = _format_code(repaired, fname, target_lang)
                if target_lang == "java" and fname.endswith(".java"):
                    repaired = _inject_java_imports(repaired)
                current[fname] = repaired
                (tmp_dir / fname).write_text(repaired, encoding="utf-8")

    if on_progress:
        on_progress("(checking…)", "done", base_total + 2, base_total + 2)

    return current


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
    schema_context: str = "",
    memory_context: str = "",
    contract_context: str = "",
    inheritance_hint: str = "",   # "class Foo(Bar):"  — injected at TOP, primacy effect
    abstract_hint: str = "",      # "abstract class Foo" — injected at TOP for abstract bases
    child_classes: list = None,   # classes that inherit FROM this one (never import them)
    plan_context: str = "",       # pre-generation reasoning plan for complex files
) -> str:
    """
    Convert one source file to target_lang.
    codebase_context — compact file-tree for cross-file awareness.
    import_graph     — what this file imports (external deps).
    module_map       — what every other project file exports (for cross-imports).
    schema_context   — project-wide class hierarchy and dependency schema (Pass 0).
    memory_context   — already-converted peer files (growing conversion memory).
    contract_context — Pass 0.1 translation contract: locked names, imports, required methods.
    inheritance_hint — deterministic subclass declaration line derived from schema.
    abstract_hint    — deterministic abstract class declaration line derived from schema.
    child_classes    — names of classes that inherit from this file's class (never import them).
    plan_context     — pre-generation reasoning plan (from _reasoning_prepass).
    """
    child_classes = child_classes or []

    ctx_block = ""
    # Contract goes FIRST so the model sees the locked decisions before anything else.
    if contract_context:
        ctx_block = f"\n\n### {contract_context}"
    if codebase_context:
        ctx_block += f"\n\n### CODEBASE STRUCTURE\n{codebase_context}"
    if module_map:
        ctx_block += f"\n\n### {module_map}"
    if import_graph:
        ctx_block += f"\n\n### THIS FILE'S SOURCE IMPORTS\n{import_graph}"
    if schema_context:
        ctx_block += f"\n\n### {schema_context}"
    if memory_context:
        ctx_block += f"\n\n### {memory_context}"

    is_main   = filename.rsplit("/", 1)[-1].startswith("main")
    base_name = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    # ── TOP-OF-PROMPT structural requirements (primacy effect) ───────────────

    # Subclass inheritance requirement
    inheritance_block = (
        f"\nINHERITANCE REQUIREMENT: The class in this file MUST be declared as:\n"
        f"  {inheritance_hint}\n"
        f"Do NOT omit the parent. Do NOT re-declare the parent's fields or methods.\n"
        f"Call the parent constructor with super().__init__(...) in __init__.\n"
    ) if inheritance_hint else ""

    # Abstract base class requirement
    abstract_block = ""
    if abstract_hint:
        if target_lang == "python":
            abstract_block = (
                f"\nABSTRACT CLASS REQUIREMENT: This class MUST be declared abstract.\n"
                f"  Add `from abc import ABC, abstractmethod` at the top.\n"
                f"  Declare as: {abstract_hint}\n"
                f"  Decorate every abstract method with @abstractmethod and give it only `pass` as body.\n"
            )
        else:
            abstract_block = (
                f"\nABSTRACT CLASS REQUIREMENT: This class MUST be declared abstract.\n"
                f"  Declare as: {abstract_hint}\n"
                f"  Mark every abstract method with the `abstract` keyword.\n"
            )

    # Concise few-shot OOP example — inheritance takes priority over abstract
    few_shot_block = ""
    if inheritance_hint and target_lang == "python":
        few_shot_block = (
            f"\n### EXAMPLE — correct OOP inheritance pattern (follow this exactly):\n"
            f"# Correct Python translation:\n"
            f"#   class Child(Parent):          # parent in parentheses, always\n"
            f"#       def __init__(self, a, b):\n"
            f"#           super().__init__(a)   # call parent constructor first\n"
            f"#           self.b = b\n"
            f"#       def do_work(self):\n"
            f"#           ...\n"
        )
    elif inheritance_hint and target_lang in ("typescript", "javascript"):
        few_shot_block = (
            f"\n### EXAMPLE — correct OOP inheritance pattern:\n"
            f"// export class Child extends Parent {{\n"
            f"//     constructor(...) {{ super(...); ... }}\n"
            f"// }}\n"
        )
    elif inheritance_hint and target_lang == "java":
        few_shot_block = (
            f"\n### EXAMPLE — correct OOP inheritance pattern:\n"
            f"// class Child extends Parent {{\n"
            f"//     public Child(...) {{ super(...); ... }}\n"
            f"// }}\n"
        )
    elif abstract_hint and target_lang == "python":
        few_shot_block = (
            f"\n### EXAMPLE — correct abstract class pattern:\n"
            f"# from abc import ABC, abstractmethod\n"
            f"# class Animal(ABC):\n"
            f"#     @abstractmethod\n"
            f"#     def speak(self) -> str:\n"
            f"#         pass   # abstract — no body\n"
        )

    # Child-import ban (never import classes that inherit FROM this file's class)
    child_ban = ""
    if child_classes:
        child_ban = (
            f"6b. NEVER import {', '.join(child_classes)} — they inherit FROM this class. "
            f"    Importing your own subclasses creates a circular import.\n"
        )

    main_rule = (
        f"9. This is the MAIN entry-point — import peer modules from the MODULE MAP "
        f"   and wire them together. Do NOT redefine their classes inline.\n"
        f"10. Use ONLY the method names shown in the NAMING section of the contract — "
        f"    NEVER invent method names or use wrong casing.\n"
        f"11. If any peer module has a saveData() / save_data() method, call it on the "
        f"    library/manager object BEFORE the exit break.\n"
    ) if is_main else ""

    # plan_block goes AFTER peer signatures (ctx_block) so the model reads the
    # correct interfaces first and the lookup reinforces what it just read.
    plan_block = (
        f"\n### CROSS-FILE REFERENCE LOOKUP — exact names extracted from peer interfaces above:\n"
        f"{plan_context}\n"
        if plan_context else ""
    )

    prompt = (
        f"You are an expert {target_lang} developer converting {source_lang} code to "
        f"clean, idiomatic {target_lang}. You never copy {source_lang} naming conventions — "
        f"you always use proper {target_lang} style.\n"
        f"{inheritance_block}"
        f"{abstract_block}"
        f"{few_shot_block}"
        f"\nRULES — every rule is mandatory:\n"
        f"1. This file is '{filename}'. It MUST contain the full {base_name} class/module body. "
        f"   Do NOT produce an empty file or a file with only import statements.\n"
        f"2. Use the TRANSLATION CONTRACT (below) for all method/field names and imports. "
        f"   Do NOT invent names — every cross-file symbol must match the contract exactly.\n"
        f"3. Copy the IMPORTS FOR THIS FILE from the contract verbatim. Do not guess paths.\n"
        f"4. Implement EVERY method in the REQUIRED METHODS list — do not skip any.\n"
        f"5. Preserve ALL logic, algorithms, and control-flow exactly.\n"
        f"6. NEVER import from main.py, main.ts, main.java, or any entry-point file.\n"
        f"{child_ban}"
        f"7. For third-party and stdlib imports use idiomatic {target_lang} equivalents.\n"
        f"8. Output ONLY the raw translated code — no markdown fences, no explanations.\n"
        + main_rule
        + _lang_rules(target_lang)
        + f"\n{ctx_block}\n"
        + plan_block
        + f"\n"
        f"### FILE TO TRANSLATE: {filename}\n"
        f"```{source_lang}\n"
        f"{code[:12000]}\n"
        f"```\n"
        f"\n"
        f"{target_lang} translation:"
    )

    if os.getenv("CODELENS_DEBUG_PROMPTS"):
        debug_path = Path(f"debug_prompt_{Path(filename).stem}.txt")
        debug_path.write_text(prompt, encoding="utf-8")
        print(f"  [DEBUG] prompt written to {debug_path}")

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
    mapping = _DEPS.get((source_lang, target_lang), {})
    target_pkgs: set[str] = set()

    for code in all_source_code.values():
        for imp in _extract_import_names(code, source_lang):
            mapped = mapping.get(imp)
            if mapped is not None:
                target_pkgs.add(mapped)

    if not target_pkgs:
        return None

    if target_lang in ("javascript", "typescript"):
        return "package.json", _npm_pkg_json(list(target_pkgs), project_name)
    return None


# ── Post-generation verification ──────────────────────────────────────────────

def _verify_consistency(
    results: dict[str, str],
    target_lang: str,
    naming: dict[str, str],
) -> list[dict]:
    """
    After all files are generated, ask the LLM to audit them for cross-file
    consistency issues. Returns a list of {"file": ..., "issue": ...} dicts.
    Empty list means no problems found (or LLM failed to parse).
    """
    MAX_CHARS_PER_FILE = 3000   # cap per file to keep the prompt bounded
    MAX_TOTAL_CHARS    = 18000

    naming_rule = "snake_case" if target_lang in _SNAKE_TARGETS else "camelCase"

    # Build file blocks in dependency-relevance order (non-manifest files first)
    file_blocks: list[str] = []
    total = 0
    for out_path, code in sorted(results.items()):
        if out_path.endswith(("package.json", "tsconfig.json")):
            continue
        excerpt = code[:MAX_CHARS_PER_FILE]
        block   = f"=== {out_path} ===\n{excerpt}"
        if total + len(block) > MAX_TOTAL_CHARS:
            # Include only the method/class signature lines for remaining files
            sigs = [
                l for l in code.splitlines()
                if re.match(r'^\s*(def |class |public |protected |private |\w+ \w+\()', l)
            ]
            block = f"=== {out_path} (signatures only) ===\n" + "\n".join(sigs[:25])
        file_blocks.append(block)
        total += len(block)

    if not file_blocks:
        return []

    files_text = "\n\n".join(file_blocks)

    # Build a compact locked-name reference from the naming map
    name_ref = ""
    if naming:
        entries = [f"  {src} → {tgt}" for src, tgt in list(naming.items())[:40]]
        name_ref = "LOCKED NAMES (use these EXACTLY for cross-file calls):\n" + "\n".join(entries) + "\n\n"

    prompt = (
        f"You are a {target_lang} code consistency auditor.\n"
        f"Your ONLY job: find cross-file bugs in these generated files.\n\n"
        f"{name_ref}"
        f"CHECK FOR:\n"
        f"1. Method called on an object that is NOT defined in that object's class\n"
        f"2. Wrong number of constructor arguments when instantiating a class\n"
        f"3. Naming convention violation ({naming_rule} required — wrong casing)\n"
        f"4. Import of a symbol that does NOT exist in the imported file\n"
        f"5. Abstract class directly instantiated\n"
        f"6. Subclass re-declares a method that should be inherited without change\n\n"
        f"FILES:\n{files_text}\n\n"
        f"Return ONLY a JSON array — no markdown fences, no explanation.\n"
        f"Empty array [] if no issues.\n"
        f'[{{"file": "filename.ext", "issue": "exact description"}}]\n\n'
        f"JSON:"
    )

    try:
        raw = _call_model(prompt, CONVERT_MODEL, timeout=180)
        m = re.search(r'\[[\s\S]*\]', raw)
        if not m:
            return []
        issues = json.loads(m.group(0))
        return [
            i for i in issues
            if isinstance(i, dict) and i.get("file") and i.get("issue")
        ]
    except Exception:
        return []


def _verify_file_consistency(
    code: str,
    filename: str,
    peer_codes: dict[str, str],
    target_lang: str,
    naming: dict[str, str],
    peer_callable: dict[str, list[str]],
) -> list[dict]:
    """
    Per-file consistency audit: verify that THIS file's cross-file method calls,
    constructor calls, and imports are consistent with what peer modules actually define.
    Uses peer_callable as ground truth for which methods exist on each peer class —
    more focused and reliable than the all-files-in-one-call approach.
    """
    if not peer_codes:
        return []

    naming_rule = "snake_case" if target_lang in _SNAKE_TARGETS else "camelCase"

    peer_blocks: list[str] = []
    for peer_path, peer_code in sorted(peer_codes.items())[:6]:
        excerpt = "\n".join(peer_code.splitlines()[:80])
        peer_blocks.append(f"=== {peer_path} ===\n{excerpt}")

    whitelist_block = ""
    if peer_callable:
        wl_lines = [
            "ALLOWED METHOD CALLS — ONLY these methods exist on each peer class.",
            "Any call to a method NOT listed here is a bug:",
        ]
        for cls, methods in peer_callable.items():
            wl_lines.append(f"  {cls}: {', '.join(methods)}")
        whitelist_block = "\n".join(wl_lines) + "\n\n"

    name_ref = ""
    if naming:
        entries = [f"  {src} → {tgt}" for src, tgt in list(naming.items())[:30]]
        name_ref = "LOCKED NAMES:\n" + "\n".join(entries) + "\n\n"

    prompt = (
        f"You are a {target_lang} code auditor. Check ONLY the file '{filename}' "
        f"for cross-file bugs against its peer modules.\n\n"
        f"{name_ref}"
        f"{whitelist_block}"
        f"CHECK FOR in '{filename}':\n"
        f"1. Any method called on a peer object that is NOT in that peer's allowed list above\n"
        f"2. Wrong number of constructor arguments when instantiating a peer class\n"
        f"3. Naming convention violation ({naming_rule} required — wrong casing on cross-file calls)\n"
        f"4. Import of a symbol that does NOT exist in the imported file\n\n"
        f"PEER FILES:\n" + "\n\n".join(peer_blocks) + "\n\n"
        f"FILE TO AUDIT ({filename}):\n{code[:6000]}\n\n"
        f"Return ONLY a JSON array — no markdown, no explanation.\n"
        f"Empty array [] if no issues found.\n"
        f'[{{"file": "{filename}", "issue": "exact description"}}]\n\n'
        f"JSON:"
    )

    try:
        raw = _call_model(prompt, CONVERT_MODEL, timeout=120)
        m   = re.search(r'\[[\s\S]*\]', raw)
        if not m:
            return []
        issues = json.loads(m.group(0))
        return [
            i for i in issues
            if isinstance(i, dict) and i.get("file") and i.get("issue")
        ]
    except Exception:
        return []


def _fix_consistency_issues(
    results: dict[str, str],
    issues: list[dict],
    target_lang: str,
) -> dict[str, str]:
    """
    For each file that has reported consistency issues, do a targeted repair
    prompt that shows the file + its peers and asks for exactly the listed fixes.
    """
    fixed = dict(results)

    # Group issues by file
    by_file: dict[str, list[str]] = {}
    for issue in issues:
        fname = issue.get("file", "")
        # Match file key even if path separators differ slightly
        matched = next(
            (k for k in fixed if k == fname or k.endswith("/" + fname) or k.endswith("\\" + fname)),
            None,
        )
        if matched:
            by_file.setdefault(matched, []).append(issue.get("issue", ""))

    for fname, file_issues in by_file.items():
        code = fixed[fname]

        # Collect first 100 lines of every peer for cross-reference
        peer_blocks: list[str] = []
        for out_path, peer_code in fixed.items():
            if out_path == fname or out_path.endswith(("package.json", "tsconfig.json")):
                continue
            excerpt = "\n".join(peer_code.splitlines()[:100])
            peer_blocks.append(f"--- {out_path} ---\n{excerpt}")

        issues_text  = "\n".join(f"- {iss}" for iss in file_issues)
        peers_text   = "\n\n".join(peer_blocks[:5])

        prompt = (
            f"You are an expert {target_lang} developer fixing specific cross-file "
            f"consistency bugs.\n\n"
            f"ISSUES TO FIX in {fname}:\n{issues_text}\n\n"
            f"PEER FILES (use these for correct method names and signatures):\n"
            f"{peers_text}\n\n"
            f"CURRENT FILE ({fname}):\n{code[:8000]}\n\n"
            f"Fix ONLY the listed issues. Preserve all logic.\n"
            f"Output ONLY the complete fixed {target_lang} file. No fences. No explanation."
        )

        try:
            repaired = _strip_fences(_call_model(prompt, CONVERT_MODEL, timeout=240))
            if repaired.strip():
                fixed[fname] = repaired
        except Exception:
            pass

    return fixed


def _generate_cpp_headers(results: dict[str, str]) -> dict[str, str]:
    """
    For each .cpp in results that has no matching .h, make one focused LLM call
    to generate the header: #pragma once + class declaration with all method
    bodies replaced by semicolons.  Returns {h_path: header_content}.
    """
    headers: dict[str, str] = {}

    for cpp_path, cpp_code in results.items():
        if not cpp_path.endswith(".cpp"):
            continue
        h_path = cpp_path[:-4] + ".h"
        if h_path in results:
            continue

        prompt = (
            f"You are an expert C++ developer. Given this .cpp implementation file, "
            f"generate ONLY the corresponding .h header file.\n\n"
            f"RULES:\n"
            f"- First line: #pragma once\n"
            f"- Add #include directives for all system headers the class needs "
            f"(<string>, <vector>, <memory>, <iostream>, etc.)\n"
            f"- Add #include \"ClassName.h\" for every other project class the header references\n"
            f"- Declare the class with all public / protected / private sections\n"
            f"- Replace EVERY method body with a semicolon `;` — declarations only\n"
            f"- Keep the exact same access specifiers (public:, protected:, private:)\n"
            f"- Output ONLY the raw header code. No markdown fences. No explanation.\n\n"
            f"IMPLEMENTATION ({cpp_path}):\n{cpp_code[:8000]}\n\n"
            f".h header:"
        )

        try:
            raw = _strip_fences(_call_model(prompt, CONVERT_MODEL, timeout=120))
            if raw.strip():
                headers[h_path] = raw
        except Exception:
            pass

    return headers


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

    # Auto-detect source language from collected files if not explicitly provided.
    if not source_lang:
        lang_counts: dict[str, int] = {}
        for f in files:
            lg = detect_language(f)
            if lg:
                lang_counts[lg] = lang_counts.get(lg, 0) + 1
        if lang_counts:
            source_lang = max(lang_counts, key=lambda k: lang_counts[k])

    # Pass 0 — read the whole project first; build class/dependency schema
    if on_progress:
        on_progress("(analyzing project…)", "converting", 1, 0)
    schema = _analyze_project(files, root, source_lang or "")

    # Pass 0.5 — topological sort: dependencies first, entry points last
    files = _topological_sort(files, root, schema)

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

    # Synthesize header-only constant files (.h with only #define/const, no class body).
    # Add them to results immediately and register their symbols in module_symbols so
    # all subsequent file prompts know how to import from them.
    synth_out_map: dict[str, str] = {}   # src_rel → out_rel for synthesized headers
    for h_path in sorted(root.rglob("*.h")):
        if any(part in SKIP_DIRS for part in h_path.relative_to(root).parts):
            continue
        try:
            h_code = h_path.read_text(encoding="utf-8", errors="replace")
            if not _is_constants_header(h_code):
                continue
            h_rel = h_path.relative_to(root).as_posix()
            synthesis = _synth_constants_file(h_code, h_rel, target_lang)
            if synthesis:
                out_filename, content, syms = synthesis
                results[out_filename] = content
                module_symbols[h_rel] = syms
                synth_out_map[h_rel]  = out_filename
        except Exception:
            pass

    module_map = _build_module_map(module_symbols, target_lang)

    # Replace the model-generated dependency graph with one built from actual
    # import/include parsing — reliable for all supported source languages.
    _src = (source_lang or "").lower()
    if _src in ("cpp", "c"):
        parsed_deps = _build_cpp_deps(files, root, synth_out_map)
        schema.setdefault("dependencies", {}).update(parsed_deps)
    elif _src in ("java", "python", "javascript", "typescript"):
        parsed_deps = _build_source_deps(files, root, _src)
        schema.setdefault("dependencies", {}).update(parsed_deps)

    # Pass 0.1 — translation contract: lock in naming, imports, and required methods
    # across all files before any file is converted.
    if on_progress:
        on_progress("(building translation contract…)", "converting", len(files) + 3, 1)
    out_path_map: dict[str, str] = {}
    for fpath in files:
        src_rel = fpath.relative_to(root).as_posix()
        parts   = src_rel.rsplit(".", 1)
        out_path_map[src_rel] = (parts[0] if len(parts) > 1 else src_rel) + target_ext
    out_path_map.update(synth_out_map)

    contract   = _generate_translation_contract(
        files, root, source_lang or "", target_lang, schema, target_ext, out_path_map
    )
    import_map = _build_import_map(
        files, root, schema, target_lang, target_ext, module_symbols, synth_out_map
    )

    # Override the LLM-generated required_methods and naming with deterministic
    # values parsed directly from source files — no LLM variability.
    if _src in ("cpp", "c"):
        header_req = _build_header_required_methods(files, root, target_lang, out_path_map)
        if header_req:
            contract.setdefault("required_methods", {}).update(header_req)
        det_naming = _build_deterministic_naming(files, root, schema, target_lang)
        if det_naming:
            contract["naming"] = det_naming
    elif _src in ("java", "python", "javascript", "typescript"):
        src_req = _build_source_required_methods(files, root, _src, target_lang, out_path_map)
        if src_req:
            contract.setdefault("required_methods", {}).update(src_req)
        src_naming = _build_source_naming(files, root, _src, schema, target_lang)
        if src_naming:
            contract["naming"] = src_naming

    # Persistence enforcement: if a source file defines save/load methods they
    # MUST appear in the output. Add them to required_methods by name so the
    # completeness checker catches and repairs any omission.
    _persist_tgt: dict[str, dict[str, str]] = {
        "python":     {
            "saveData": "save_data", "save_data": "save_data",
            "loadData": "load_data", "load_data": "load_data",
            "saveToFile": "save_to_file", "loadFromFile": "load_from_file",
        },
        "javascript": {
            "saveData": "saveData", "save_data": "saveData",
            "loadData": "loadData", "load_data": "loadData",
            "saveToFile": "saveToFile", "loadFromFile": "loadFromFile",
        },
        "typescript": {
            "saveData": "saveData", "save_data": "saveData",
            "loadData": "loadData", "load_data": "loadData",
            "saveToFile": "saveToFile", "loadFromFile": "loadFromFile",
        },
        "java": {
            "saveData": "saveData", "save_data": "saveData",
            "loadData": "loadData", "load_data": "loadData",
            "saveToFile": "saveToFile", "loadFromFile": "loadFromFile",
        },
    }
    tgt_persist_map = _persist_tgt.get(target_lang, {})
    for fpath in files:
        src_rel_p  = fpath.relative_to(root).as_posix()
        out_rel_p  = out_path_map.get(src_rel_p)
        if not out_rel_p:
            continue
        try:
            src_text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        req_list = contract.setdefault("required_methods", {}).setdefault(out_rel_p, [])
        for src_name, tgt_name in tgt_persist_map.items():
            if re.search(rf'\b{re.escape(src_name)}\s*\(', src_text) and tgt_name not in req_list:
                req_list.append(tgt_name)

    conversion_memory:   dict[str, str]                  = {}   # grows as each file is converted
    peer_callable_by_out: dict[str, dict[str, list[str]]] = {}   # out_rel → {class: [methods]}

    # C++ header skeleton pre-pass: before converting any .cpp, populate conversion_memory
    # with minimal skeleton .h files so every dependent .cpp sees the class interface
    # for its dependencies and knows NOT to redeclare those classes in its own .cpp body.
    # These skeletons are in conversion_memory ONLY — _generate_cpp_headers (post-loop)
    # will regenerate them from the completed .cpp implementations, producing correct types.
    if target_lang == "cpp":
        for fpath in files:
            src_rel      = fpath.relative_to(root).as_posix()
            out_cpp_rel  = out_path_map.get(src_rel, "")
            if not out_cpp_rel.endswith(".cpp"):
                continue
            out_h_rel    = out_cpp_rel[:-4] + ".h"
            class_name   = fpath.stem
            cls_info     = schema.get("classes", {}).get(class_name, {})
            parent       = cls_info.get("inherits") or cls_info.get("parent")

            h_lines = [
                "#pragma once",
                "#include <string>",
                "#include <vector>",
                "#include <memory>",
                "",
            ]
            if parent:
                h_lines.append(f'#include "{parent}.h"')
            inherit_clause = f" : public {parent}" if parent else ""
            h_lines.append(f"class {class_name}{inherit_clause} {{")
            h_lines.append("public:")

            # Method stubs from contract (already built deterministically from source)
            req_methods = contract.get("required_methods", {}).get(out_cpp_rel, [])
            for mspec in req_methods:
                mname = mspec.split("(")[0].strip()
                if mname:
                    h_lines.append(f"    void {mname}();  // declaration")

            h_lines.extend(["};", ""])
            conversion_memory[out_h_rel] = "\n".join(h_lines)

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

            # Schema context + growing conversion memory
            schema_ctx   = _schema_context_block(schema, rel)
            current_deps = schema.get("dependencies", {}).get(rel, [])
            mem_ctx      = _memory_block(conversion_memory, current_deps, target_lang)

            # Peer callable whitelist — built from already-converted outputs (deterministic)
            peer_callable  = _build_peer_callable_methods(
                conversion_memory, current_deps, target_lang, out_path_map
            )

            # Translation contract block for this specific output file
            contract_block = _contract_context_block(contract, import_map, out_rel, peer_callable)

            # Reasoning pre-pass: planning step for complex files (2+ deps or main)
            is_main_file = fpath.stem.lower() in ("main", "__main__", "index", "app")
            plan_ctx = ""
            if conversion_memory and (len(current_deps) >= 2 or is_main_file):
                plan_ctx = _reasoning_prepass(
                    code, lang, target_lang, mem_ctx, contract_block, rel
                )

            # Compute structural hints for this class from schema (all deterministic)
            stem     = Path(out_rel).stem
            cls_info = schema.get("classes", {}).get(stem, {})

            parent           = cls_info.get("inherits")
            is_abstract      = cls_info.get("abstract", False)
            inheritance_hint = _make_inheritance_hint(stem, parent, target_lang) if parent else ""
            abstract_hint    = _make_abstract_hint(stem, target_lang) if is_abstract and not parent else ""

            # Classes that inherit FROM this class — never import them (circular)
            child_classes = [
                cls_name for cls_name, info in schema.get("classes", {}).items()
                if info.get("inherits") == stem
            ]

            converted = convert_single_file(
                code=code,
                source_lang=lang,
                target_lang=target_lang,
                filename=rel,
                codebase_context=context,
                import_graph=import_note,
                module_map=this_map,
                schema_context=schema_ctx,
                memory_context=mem_ctx,
                contract_context=contract_block,
                inheritance_hint=inheritance_hint,
                abstract_hint=abstract_hint,
                child_classes=child_classes,
                plan_context=plan_ctx,
            )

            # Completeness check — re-prompt once if required methods or enum values are missing
            req_methods = contract.get("required_methods", {}).get(out_rel, [])
            file_stem_lower = Path(out_rel).stem.lower()
            file_enums = {
                fqn: vals for fqn, vals in schema.get("enums", {}).items()
                if fqn.split(".")[0].lower() == file_stem_lower or fqn.lower() == file_stem_lower
            } or None
            if req_methods or file_enums:
                missing = _check_completeness(converted, req_methods, target_lang, file_enums)
                if missing:
                    converted = _complete_missing_methods(
                        converted, missing, code, lang, target_lang, contract_block
                    )

            # Persistence safety net: stub any called-but-undefined save/load methods
            converted = _inject_persistence_stubs(converted, target_lang)

            # Post-process: fix missing inheritance declarations (all source languages)
            converted = _fix_missing_inheritance(converted, schema, out_rel, target_lang)

            # Post-process: fix Color.CONSTANT → CONSTANT for Python constants modules
            synth_syms = {
                Path(v).stem: module_symbols.get(k, [])
                for k, v in synth_out_map.items()
            }
            converted = _fix_color_module_access(converted, synth_syms, target_lang)

            # Post-process: fix camelCase call sites in ALL output files
            converted = _fix_callsite_casing(converted, contract.get("naming", {}), target_lang)

            # Post-process: detect and repair unevaluated ternaries inside f-strings (Python only)
            converted = _fix_python_fstring_ternaries(converted, target_lang, rel)

            results[out_rel]              = converted
            conversion_memory[out_rel]    = converted            # grow the memory
            peer_callable_by_out[out_rel] = peer_callable        # store for verification pass

            if on_progress:
                on_progress(rel, "done", len(files), i + 1)

        except Exception as exc:
            err_comment = {
                "python":     f"# ERROR: {exc}",
                "javascript": f"// ERROR: {exc}",
                "typescript": f"// ERROR: {exc}",
                "java":       f"// ERROR: {exc}",
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

    # C++ post-pass: generate missing .h headers + inject missing system #includes.
    # Runs after stitching so every .cpp is finalised before we generate headers,
    # and before verification so the compile check has correct header files.
    if target_lang == "cpp":
        if on_progress:
            on_progress("(generating C++ headers…)", "converting", len(results) + 2, len(results) + 1)
        headers = _generate_cpp_headers(results)
        results.update(headers)
        results = {
            k: (_inject_cpp_includes(v) if k.endswith(".cpp") else v)
            for k, v in results.items()
        }
        if on_progress:
            on_progress("(generating C++ headers…)", "done", len(results) + 2, len(results) + 2)

    # Verification pass: per-file consistency check + targeted repair.
    # Each file is audited individually against its peers, with the peer_callable
    # whitelist (built deterministically from converted outputs) as ground truth.
    # This scales with project size and catches method-name hallucinations that
    # the all-files-in-one-call approach misses for larger codebases.
    if len(results) > 1:
        if on_progress:
            on_progress("(verifying cross-file consistency…)", "converting", len(results) + 2, len(results) + 1)
        manifest_exts = ("package.json", "tsconfig.json")
        all_issues: list[dict] = []
        for out_path, code in results.items():
            if out_path.endswith(manifest_exts):
                continue
            peers = {
                p: c for p, c in results.items()
                if p != out_path and not p.endswith(manifest_exts)
            }
            file_callable = peer_callable_by_out.get(out_path, {})
            file_issues   = _verify_file_consistency(
                code, out_path, peers, target_lang,
                contract.get("naming", {}), file_callable,
            )
            all_issues.extend(file_issues)

        if all_issues:
            results = _fix_consistency_issues(results, all_issues, target_lang)
            repaired_files = {i["file"] for i in all_issues if "file" in i}
            # Build a stem → source_code lookup so we can feed the repair completeness check
            _stem_to_src: dict[str, str] = {
                Path(src_rel).stem: src_code
                for src_rel, src_code in original_code.items()
            }
            for out_rel_r in repaired_files:
                key = next(
                    (k for k in results if k == out_rel_r or k.endswith("/" + out_rel_r)),
                    None,
                )
                if key:
                    results[key] = _fix_callsite_casing(
                        results[key], contract.get("naming", {}), target_lang
                    )
                    # Re-check completeness: the repair LLM may have stubbed or dropped methods
                    req_methods = contract.get("required_methods", {}).get(key, [])
                    key_stem_lower = Path(key).stem.lower()
                    key_enums = {
                        fqn: vals for fqn, vals in schema.get("enums", {}).items()
                        if fqn.split(".")[0].lower() == key_stem_lower or fqn.lower() == key_stem_lower
                    } or None
                    if req_methods or key_enums:
                        still_missing = _check_completeness(
                            results[key], req_methods, target_lang, key_enums
                        )
                        if still_missing:
                            src_code = _stem_to_src.get(Path(key).stem, "")
                            results[key] = _complete_missing_methods(
                                results[key], still_missing, src_code,
                                source_lang or "java", target_lang, ""
                            )
        if on_progress:
            on_progress("(verifying cross-file consistency…)", "done", len(results) + 2, len(results) + 2)

    # Post-process: strip bare Java imports and inject missing stdlib imports
    if target_lang == "java":
        results = {
            k: (_inject_java_imports(_sanitize_java_imports(v)) if k.endswith(".java") else v)
            for k, v in results.items()
        }

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

    # Layer 2+3: format + compile-check-repair
    results = _postprocess(results, target_lang, on_progress)

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
