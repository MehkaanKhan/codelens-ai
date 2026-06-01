"""
Parse a codebase into function/class-level chunks using Tree-sitter.
Output: .tmp/chunks.jsonl

Usage: python tools/parse_codebase.py --repo-path /path/to/repo [--output .tmp/chunks.jsonl]
"""

import argparse
import json
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".rs": "rust",
    ".go": "go",
}

SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build", ".tmp"}

# Node types that represent a meaningful chunk per language
CHUNK_TYPES = {
    "python":     {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "method_definition", "arrow_function", "class_declaration"},
    "typescript": {"function_declaration", "method_definition", "arrow_function", "class_declaration"},
    "java":       {"method_declaration", "class_declaration"},
    "c":          {"function_definition"},
    "cpp":        {"function_definition"},
    "rust":       {"function_item", "impl_item"},
    "go":         {"function_declaration", "method_declaration"},
}

# Child field or node type that holds the function/class name
NAME_CHILD_TYPES = {"identifier", "property_identifier", "field_identifier", "qualified_identifier"}


def get_name(node) -> str:
    """Extract the name identifier from a function/class node."""
    # First try named child called 'name'
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode(errors="replace")
    # Fallback: find first identifier child
    for child in node.children:
        if child.type in NAME_CHILD_TYPES:
            return child.text.decode(errors="replace")
    return "anonymous"


def collect_chunks(node, source: bytes, language: str, chunks: list, depth: int = 0):
    """Recursively walk the AST and collect chunk nodes."""
    target_types = CHUNK_TYPES.get(language, set())

    if node.type in target_types:
        name = get_name(node)
        code = source[node.start_byte:node.end_byte].decode(errors="replace")
        chunks.append({
            "function_name": name,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "code": code,
        })
        # Don't recurse into top-level chunks to avoid nested function duplication
        # (except for class bodies — we want methods inside classes too)
        if node.type not in {"class_definition", "class_declaration", "impl_item"}:
            return

    for child in node.children:
        collect_chunks(child, source, language, chunks, depth + 1)


def load_language(lang_name: str):
    try:
        if lang_name == "python":
            import tree_sitter_python as m
        elif lang_name == "javascript":
            import tree_sitter_javascript as m
        elif lang_name == "typescript":
            import tree_sitter_typescript as m
            from tree_sitter import Language
            return Language(m.language_typescript())
        elif lang_name == "java":
            import tree_sitter_java as m
        elif lang_name == "c":
            import tree_sitter_c as m
        elif lang_name == "cpp":
            import tree_sitter_cpp as m
        elif lang_name == "rust":
            import tree_sitter_rust as m
        elif lang_name == "go":
            import tree_sitter_go as m
        else:
            return None
        from tree_sitter import Language
        return Language(m.language())
    except Exception:
        return None


def parse_file(file_path: Path, language: str) -> list[dict]:
    source = file_path.read_bytes()
    lang = load_language(language)

    if lang:
        try:
            from tree_sitter import Parser
            parser = Parser(lang)
            tree = parser.parse(source)
            chunks = []
            collect_chunks(tree.root_node, source, language, chunks)
            if chunks:
                result = []
                for c in chunks:
                    result.append({
                        "file_path": str(file_path),
                        "function_name": c["function_name"],
                        "language": language,
                        "start_line": c["start_line"],
                        "end_line": c["end_line"],
                        "code": c["code"],
                    })
                return result
        except Exception:
            pass

    # Fallback: whole file as one chunk
    try:
        text = source.decode(errors="replace")
        return [{
            "file_path": str(file_path),
            "function_name": "__file__",
            "language": language,
            "start_line": 1,
            "end_line": len(text.splitlines()),
            "code": text,
        }]
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    # Default output is always relative to the repo root (not CWD)
    _repo_root = Path(__file__).parent.parent.resolve()
    _default_out = str(_repo_root / ".tmp" / "chunks.jsonl")
    parser.add_argument("--output", default=_default_out)
    args = parser.parse_args()

    repo = Path(args.repo_path).resolve()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    all_chunks = []
    file_count = 0

    for file_path in repo.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in SKIP_DIRS for part in file_path.parts):
            continue
        language = SUPPORTED_EXTENSIONS.get(file_path.suffix.lower())
        if not language:
            continue

        chunks = parse_file(file_path, language)

        # Store paths RELATIVE to the repo root so source citations work correctly
        # in the VS Code extension's file anchor links.
        for chunk in chunks:
            try:
                chunk["file_path"] = file_path.relative_to(repo).as_posix()
            except ValueError:
                chunk["file_path"] = str(file_path)  # fallback to absolute if outside repo

        all_chunks.extend(chunks)
        file_count += 1

    with open(output, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk) + "\n")

    print(f"Parsed {len(all_chunks)} chunks from {file_count} files in {repo}")
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
