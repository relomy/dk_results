# Testing & verification

How to run this repo's checks, and the one gotcha that stops them cold.

## Completion checks

Run before reporting any change complete. Use the full suite when the change is
broad; the relevant subset when it's narrow.

- `uv run pytest` — the repository-wide test command.
- `uv run ruff format --check --exclude .ci .`
- `uv run ruff check .`
- `uv run ty check`

## Gotcha: dfs-common is an editable sibling checkout

`dfs-common` is sourced as an editable path dependency in `[tool.uv.sources]`:

```toml
dfs-common = { path = "../dfs_common", editable = true }
```

So `uv` expects the private `relomy/dfs-common` repo checked out as a sibling
directory at `../dfs_common`, next to this repo. Every `uv` command builds the
venv first, so `pytest`, `ruff`, and `ty` all fail *before running a single
test* when that checkout is missing:

- `Distribution not found at: file:///.../dfs_common` — the sibling checkout
  isn't there.
- `fatal: could not read Username for 'https://github.com'` — you tried to clone
  it without git credentials for the private repo.

Fix: clone `relomy/dfs-common` to `../dfs_common` (private, so you need git read
access — a token or SSH key with read scope). In a Claude Code web session, add
`relomy/dfs-common` to the session's scope first, then clone it to the sibling
path. Once it's in place, `uv sync` builds the editable install and the checks
run.
