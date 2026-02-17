import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent
_src = _repo_root / "src"
_src_str = str(_src)
if _src.is_dir() and _src_str not in sys.path:
    sys.path.insert(0, _src_str)

import dk_results.cli.draftables  # noqa: E402, F401

if __name__ == "__main__":
    pass
