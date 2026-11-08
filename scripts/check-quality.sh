#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

base_ref=${QUALITY_BASE_REF:-origin/main}
if ! git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
  echo "Quality checks require a resolvable ratchet base: $base_ref" >&2
  echo "Set QUALITY_BASE_REF to a local commit or fetch origin/main." >&2
  exit 2
fi

run() {
  echo "+ $*"
  "$@"
}

run uv run --locked --group quality ruff format --check .
run uv run --locked --group quality ruff check .
run uv run --locked --group quality ty check
run uv run --locked --group quality xenon --max-absolute B src
run uv run --locked --group quality complexity-ratchet --base "$base_ref" --worktree
