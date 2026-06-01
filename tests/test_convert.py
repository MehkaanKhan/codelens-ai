"""Quick test runner — converts tests/test_cpp to a target language and prints results."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from backend.codebase_converter import convert_codebase

TARGET = sys.argv[1] if len(sys.argv) > 1 else "python"
ROOT   = Path(__file__).parent / "test_cpp"

print(f"\n{'='*60}")
print(f"Converting test_cpp → {TARGET}")
print(f"{'='*60}\n")

def progress(path, status, total, done):
    if status in ("converting", "done", "error"):
        icon = {"converting": "⟳", "done": "✓", "error": "✗"}.get(status, " ")
        print(f"  {icon} [{done}/{total}] {path}")

results = convert_codebase(ROOT, target_lang=TARGET, on_progress=progress)

print(f"\n{'='*60}")
print(f"Output files ({len(results)} total):")
print(f"{'='*60}")

for fname, content in sorted(results.items()):
    print(f"\n{'─'*60}")
    print(f"  {fname}")
    print(f"{'─'*60}")
    print(content[:3000])
    if len(content) > 3000:
        print(f"  ... [{len(content)-3000} more chars]")
