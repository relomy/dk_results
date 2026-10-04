# Testing & verification

How to run this repo's checks, and how the `dfs-common` dependency is resolved.

## Completion checks

Run before reporting any change complete. Use the full suite when the change is
broad; the relevant subset when it's narrow.

- `uv run pytest` — the repository-wide test command.
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run ty check`

After changing the snapshot contract models
(`src/dk_results/services/snapshot_v3/models/`), regenerate the committed
schema with `uv run python export_snapshot_schema.py`; a test fails while
`contract/snapshot.schema.json` is stale.

## Golden envelopes

`contract/goldens/<scenario>.json` are complete snapshot envelopes built by the
real pipeline (injected collector, real derive, builder and validators, fixed
`generated_at`) from the hand-built bundles in
`tests/services/snapshot_scenarios.py`. `tests/services/test_snapshot_v3_goldens.py`
rebuilds each one and fails while it differs from the committed file.

After an intentional change to the emitted envelope, rewrite every golden in one
step and review the diff:

```bash
UPDATE_GOLDENS=1 uv run pytest tests/services/test_snapshot_v3_goldens.py
```

To add a scenario, write one bundle builder and add one `Scenario` entry to
`SCENARIOS` in `tests/services/snapshot_scenarios.py`, then run the command above.

## dfs-common is a git dependency

`dfs-common` is sourced from the private `relomy/dfs-common` GitHub repo in
`[tool.uv.sources]`, tracking its `main` branch:

```toml
dfs-common = { git = "https://github.com/relomy/dfs-common", branch = "main" }
```

No sibling `../dfs_common` checkout is required — `uv sync` clones the
dependency directly over HTTPS. This requires non-interactive GitHub read
access to the private repo:

- **Local dev**: a git credential helper (e.g. `gh auth login`, macOS Keychain)
  that already authenticates `https://github.com` requests.
- **Claude/Codex cloud sessions**: add `relomy/dfs-common` to the session's
  repo scope; the session's GitHub App credentials authenticate the clone
  automatically. No manual sibling clone is needed anymore.
- **CI**: the `DFS_COMMON_CHECKOUT_TOKEN` secret is rewritten into a git
  `insteadOf` URL before `uv sync` runs (see `.github/workflows/ci.yml`).

If dependency installation fails with a git authentication error, the fix is
to make sure one of the above credential sources is in place — not to clone a
sibling directory.

## Explicit dependency refreshes

The `pyproject.toml` source declaration expresses policy ("follow `main`").
`uv.lock` records the exact commit that was resolved and tested. Routine
`uv sync` / `uv run pytest` do **not** silently advance that commit — they
install whatever is already locked.

To pick up new `dfs-common` commits, refresh the lock entry explicitly:

```bash
uv lock --upgrade-package dfs-common
uv sync
uv run pytest
```

Commit the resulting `uv.lock` diff once the refreshed dependency has been
tested — that diff is meaningful (a new shared-library revision), not noise,
and should go through normal review.

## Locked verification

Use `uv sync --locked` (or `uv run --locked ...`) for any command that must
verify the environment without rewriting `uv.lock` — this is what CI runs. It
fails clearly, instead of silently re-resolving, when `pyproject.toml` and
`uv.lock` have drifted apart.

## Temporary local editable-path override

While actively developing unpublished changes in `dfs_common` itself, you can
temporarily point this repo at a sibling checkout instead of the git
dependency:

```toml
[tool.uv.sources]
dfs-common = { path = "../dfs_common", editable = true }
```

Run `uv sync` to pick it up. This is an exceptional, temporary development
step — revert `pyproject.toml` (and regenerate `uv.lock` back to the git
source) before committing, so normal local, CI, and cloud runs stay on the
git-based dependency.
