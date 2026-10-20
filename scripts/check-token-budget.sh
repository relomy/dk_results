#!/bin/sh
# Token budget check: no committed file may exceed its token budget.
#
# Canonical copy: relomy/dk_results scripts/check-token-budget.sh.
# relomy/dk_dashboard keeps a byte-identical copy; change it here first.
#
# Usage: check-token-budget.sh            check the staged files (pre-commit)
#        check-token-budget.sh PATH...    check these repo-root-relative paths (CI)
#
# Tokens = bytes / 4 of the staged blob. The budget is 5000 tokens unless the
# file's `token-budget=<N>` git attribute sets one (grandfathered files).
# Skipped: deleted files, `linguist-generated` files and binaries.
# Needs only POSIX sh and git.
set -u

LIMIT=5000

# Value of git attribute $1 for path $2, read from the index.
attr() {
  git check-attr --cached "$1" -- "$2" | sed "s/^.*: $1: //"
}

recipe() {
  case $1 in
    test_*.py | */test_*.py | *_test.py | conftest.py | */conftest.py)
      echo "  Python test: split by behaviour under test into several test_*.py files."
      echo "  Move shared fakes and builders into a helper module whose name does not"
      echo "  start with test_, so pytest does not collect it."
      ;;
    *.py)
      echo "  Python module: turn it into a package (or sibling modules) along its seams."
      echo "  Re-export the public names from the original import path so callers do"
      echo "  not change. Names that tests monkeypatch stay in the module they patch."
      ;;
    *.test.ts | *.test.tsx | *.spec.ts | *.spec.tsx)
      echo "  TS test: split by top-level describe into several *.test.ts(x) files."
      echo "  Move shared fixtures into a test kit module without a .test suffix."
      ;;
    *.ts | *.tsx)
      echo "  TS module: keep this file as a barrel that re-exports the public API"
      echo "  (export type for types) and move cohesive parts into sibling modules."
      ;;
    *.md)
      echo "  Markdown: split by H2 into linked pages, or move content that is not"
      echo "  this doc's job to the doc that owns it. Keep sections that tools read."
      ;;
    *)
      echo "  Split it into smaller files along its natural sections."
      ;;
  esac
}

script=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
cd "$(git rev-parse --show-toplevel)" || exit 2

if [ "$#" -eq 0 ]; then
  # Re-run on the NUL-delimited staged set; the --paths marker stops recursion
  # when xargs runs us with no paths.
  git diff --cached --name-only -z --diff-filter=ACMR |
    xargs -0 sh "$script" --paths || exit 1
  exit 0
fi
[ "$1" = "--paths" ] && shift

empty_tree=$(git hash-object -t tree /dev/null)
failed=0
for path in "$@"; do
  case $(attr linguist-generated "$path") in set | true) continue ;; esac
  bytes=$(git cat-file -s ":$path" 2>/dev/null) || continue
  budget=$(attr token-budget "$path")
  case $budget in '' | *[!0-9]*) budget=$LIMIT ;; esac
  [ "$bytes" -gt $((budget * 4)) ] || continue
  # git's binary detection on the staged blob: numstat prints "-" for binaries.
  case $(git diff --cached --numstat "$empty_tree" -- "$path") in -*) continue ;; esac
  tokens=$(((bytes + 3) / 4))
  echo "$path: $tokens tokens, budget $budget, over by $((tokens - budget))" >&2
  recipe "$path" >&2
  failed=1
done
if [ "$failed" -ne 0 ]; then
  echo "Token budget exceeded (tokens = bytes / 4)." >&2
  echo "See the Token budget section linked from AGENTS.md." >&2
fi
exit "$failed"
