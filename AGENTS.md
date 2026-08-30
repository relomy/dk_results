# Repository Instructions

dk_results is operational tooling for DraftKings contest tracking, Google Sheets
updates, and Discord notifications.

## Essentials

- Run everything through `uv` (Python `>=3.11,<3.12`); `uv sync` builds the venv.
- Source in `src/`, tests in `tests/`.
- `dfs-common` is a private git dependency; read `docs/TESTING.md` when a `uv`
  command fails while building the venv.
- Complexity regressions: `uv run complexity-ratchet --base origin/main --worktree`.

## Further instructions

Read these when the task calls for them:

- **Testing & verification** — `docs/TESTING.md`: the checks to run before
  reporting a change complete, and the `dfs-common` build gotcha.
- **Code conventions** — `docs/CONVENTIONS.md`: change size, seams, and
  repository boundaries.
- **Delivery workflow** — `docs/WORKFLOW.md`: commit message format and handoff
  report.

## Agent skills

### Issue tracker

When creating, reading, updating, labeling, commenting on, or closing an issue, use GitHub Issues for `relomy/dk_results`. Read `docs/agents/issue-tracker.md` first for the command conventions.

### Triage labels

When triaging an issue or changing its triage label, read `docs/agents/triage-labels.md` and use its mapping.

### Domain docs

Before exploring an unfamiliar area or making a design/refactor decision, read `docs/agents/domain.md`; it directs you to `docs/CONTEXT.md` and relevant ADRs for this single-context repo.
