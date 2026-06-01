"""
Build a file-level dependency graph from import statements.
Output: .tmp/graph.json  (D3-compatible: {nodes, links})

Usage: python tools/build_graph.py --repo-path /path/to/repo [--output .tmp/graph.json]
"""

import argparse
import json
import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".java": "java",
    ".c":    "c",
    ".cpp":  "cpp",
    ".rs":   "rust",
    ".go":   "go",
}

SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build", ".tmp"}

# Regex patterns that extract the imported module/path string per language.
# Each pattern must have a named group `mod`.
IMPORT_PATTERNS = {
    "python": [
        re.compile(r"^\s*import\s+(?P<mod>[\w.]+)", re.MULTILINE),
        re.compile(r"^\s*from\s+(?P<mod>[\w.]+)\s+import", re.MULTILINE),
    ],
    "javascript": [
        re.compile(r"""(?:import\s+.*?\s+from\s+|require\s*\(\s*)['"](?P<mod>[^'"]+)['"]"""),
    ],
    "typescript": [
        re.compile(r"""(?:import\s+.*?\s+from\s+|require\s*\(\s*)['"](?P<mod>[^'"]+)['"]"""),
    ],
    "java": [
        re.compile(r"^\s*import\s+(?P<mod>[\w.]+)\s*;", re.MULTILINE),
    ],
    "c": [
        re.compile(r'^\s*#include\s+"(?P<mod>[^"]+)"', re.MULTILINE),
    ],
    "cpp": [
        re.compile(r'^\s*#include\s+"(?P<mod>[^"]+)"', re.MULTILINE),
    ],
    "rust": [
        re.compile(r"^\s*use\s+(?P<mod>[\w:]+)", re.MULTILINE),
    ],
    "go": [
        re.compile(r'"(?P<mod>[^"]+)"'),
    ],
}


def extract_imports(source: str, language: str) -> list[str]:
    patterns = IMPORT_PATTERNS.get(language, [])
    seen = set()
    mods = []
    for pat in patterns:
        for m in pat.finditer(source):
            mod = m.group("mod")
            if mod not in seen:
                seen.add(mod)
                mods.append(mod)
    return mods


def resolve_import(mod: str, source_file: Path, language: str, all_files: set[Path]) -> Path | None:
    """Try to map an import string to an actual file in the repo."""
    if language == "python":
        # Relative dotted path → file path
        rel = Path(mod.replace(".", "/"))
        candidates = [rel.with_suffix(".py"), rel / "__init__.py"]
        for c in candidates:
            for f in all_files:
                if f.as_posix().endswith(c.as_posix()):
                    return f

    elif language in ("javascript", "typescript"):
        if not mod.startswith("."):
            return None  # third-party module, skip
        base = (source_file.parent / mod).resolve()
        ext = ".ts" if language == "typescript" else ".js"
        for candidate in [base, base.with_suffix(ext), base / ("index" + ext)]:
            if candidate in all_files:
                return candidate

    elif language in ("c", "cpp"):
        base = source_file.parent / mod
        if base in all_files:
            return base

    return None


def build_graph(repo_path: Path) -> dict:
    all_files: set[Path] = set()
    file_meta: dict[Path, dict] = {}

    # Collect all supported files
    for f in repo_path.rglob("*"):
        if not f.is_file():
            continue
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        lang = SUPPORTED_EXTENSIONS.get(f.suffix.lower())
        if not lang:
            continue
        all_files.add(f)
        file_meta[f] = {"language": lang}

    nodes = []
    node_ids: dict[Path, str] = {}

    for f in sorted(all_files):
        node_id = f.relative_to(repo_path).as_posix()
        node_ids[f] = node_id
        nodes.append({
            "id": node_id,
            "language": file_meta[f]["language"],
            "label": f.name,
        })

    links = []
    seen_links: set[tuple[str, str]] = set()

    for f in sorted(all_files):
        lang = file_meta[f]["language"]
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        imports = extract_imports(source, lang)
        for mod in imports:
            target = resolve_import(mod, f, lang, all_files)
            if target is None or target == f:
                continue
            src_id = node_ids[f]
            tgt_id = node_ids[target]
            key = (src_id, tgt_id)
            if key not in seen_links:
                seen_links.add(key)
                links.append({"source": src_id, "target": tgt_id})

    return {"nodes": nodes, "links": links}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--output", default=".tmp/graph.json")
    args = parser.parse_args()

    repo = Path(args.repo_path).resolve()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    graph = build_graph(repo)
    output.write_text(json.dumps(graph, indent=2), encoding="utf-8")

    print(f"Graph: {len(graph['nodes'])} nodes, {len(graph['links'])} links -> {output}")


if __name__ == "__main__":
    main()
