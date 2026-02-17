import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent
_src = _repo_root / "src"
_src_str = str(_src)
if _src.is_dir() and _src_str not in sys.path:
    sys.path.insert(0, _src_str)

from dk_results.cli.find_new_double_ups import main  # noqa: E402

if __name__ == "__main__":
    main()
