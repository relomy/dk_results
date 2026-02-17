import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PKG_ROOT = SRC_ROOT / "dk_results"

for path in (REPO_ROOT, SRC_ROOT, PKG_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
