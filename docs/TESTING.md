# Testing & verification

How to run this repo's checks, and the one gotcha that stops them cold.

## Completion checks

Run before reporting any change complete. Use the full suite when the change is
broad; the relevant subset when it's narrow.

- `uv run pytest` — the repository-wide test command.
- `uv run ruff format --check --exclude .ci .`
- `uv run ruff check .`
- `uv run ty check`

## Gotcha: dfs-common is a private git dependency

`dfs-common` is sourced from a private repo (`relomy/dfs-common`, branch `main`)
in `[tool.uv.sources]`. Every `uv` command builds the venv first, so `pytest`,
`ruff`, and `ty` all fail *before running a single test* when the environment
can't fetch it:

- `fatal: could not read Username for 'https://github.com'` — no git credentials
  for the private repo.
- `Distribution not found at: file:///.../dfs_common` — an older path-based
  source expecting a sibling checkout that isn't there.

Fix: give the environment read access to `relomy/dfs-common` — a GitHub token or
SSH key with read scope. In a Claude Code web session, add the repo to the
session's scope first. Then `uv lock` / `uv sync` resolve it and the checks run.
