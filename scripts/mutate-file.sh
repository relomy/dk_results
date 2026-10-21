#!/bin/sh
# Mutation-test ONE source file against chosen tests with mutmut 3.
#
# Usage: uv run --group quality scripts/mutate-file.sh SRC_FILE TEST_PATH...
#   e.g. uv run --group quality scripts/mutate-file.sh \
#          src/dk_results/analytics/optimizer.py tests/analytics/test_optimizer.py
#
# mutmut 3 has no CLI for the file or tests: it reads them from the config in the
# working directory. This writes a throwaway, gitignored setup.cfg for the run and
# removes it on exit; `mutants/` (mutmut's work dir) is wiped first so each run
# is fresh. Prints every survivor with its diff, then the score line.
# Run from the repo root; `uv run` puts mutmut on PATH.
set -eu

[ "$#" -ge 2 ] || { sed -n '3,6p' "$0" >&2; exit 2; }
SRC=$1
shift
command -v mutmut >/dev/null || { echo "run via: uv run --group quality $0 ..." >&2; exit 2; }
[ -f "$SRC" ] || { echo "not a file: $SRC" >&2; exit 2; }
[ ! -e setup.cfg ] || { echo "setup.cfg exists; this script owns it, remove it first" >&2; exit 2; }

trap 'rm -f setup.cfg' EXIT
{
  echo "[mutmut]"
  echo "source_paths=$SRC"
  printf 'also_copy=\n    src/\n    tests/\n'
  echo "pytest_add_cli_args_test_selection="
  for t in "$@"; do echo "    $t"; done
} >setup.cfg

rm -rf mutants
mutmut run
mutmut results --all true >mutants/results.txt
ids=$(sed -n 's/^ *\(.*\): survived$/\1/p' mutants/results.txt)
for id in $ids; do
  echo "=== $id"
  mutmut show "$id" | grep -E '^[-+] '
done
killed=$(grep -c ': killed' mutants/results.txt || true)
total=$(grep -c ': ' mutants/results.txt || true)
echo "mutation score: $killed/$total killed;" \
  "$(grep -c ': survived' mutants/results.txt || true) survived"
