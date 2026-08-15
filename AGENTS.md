# Repository Instructions

## Scope

Apply these instructions to all work under `dk_results/`.

## Repository Context

- Stack: Python
- Python: `>=3.11,<3.12`
- Package manager / runner: `uv`
- Source code: `src/`
- Tests: `tests/`
- Local dependency: `dfs-common` from `../dfs_common` (editable source)

## Working style

- Make the smallest safe change that solves the request.
- Prefer existing code and seams before adding abstractions.
- Keep unrelated refactors out of the change.
- Ask before changing public outputs or integrations.

## Change boundaries

- Keep edits in this repository.
- Ask before changing `../dfs_common` or any other repository.

## Completion

Before reporting a change complete:

- Run the relevant tests for the touched functionality; use the full suite when the scope is broad.
- Run `uv run ruff format --check --exclude .ci .`.
- Run `uv run ruff check .`.
- Run `uv run ty check`.
- Report every command run and every failure with its exact command and a concise summary.

The repository-wide test command is `uv run pytest`.

## Commit messages

- Use this format for commits: `type(scope): short summary`.
- Keep `type` lowercase (`feat`, `fix`, `test`, `docs`, `chore`, etc.); make the summary imperative and concise.

## Handoff

In the final response, state:

- what changed, including files and behavior;
- what commands were run and whether they passed;
- any remaining risk or follow-up.

## Agent skills

### Issue tracker

When creating, reading, updating, labeling, commenting on, or closing an issue, use GitHub Issues for `relomy/dk_results`. Read `docs/agents/issue-tracker.md` first for the command conventions.

### Triage labels

When triaging an issue or changing its triage label, read `docs/agents/triage-labels.md` and use its mapping.

### Domain docs

Before exploring an unfamiliar area or making a design/refactor decision, read `docs/agents/domain.md`; it directs you to `docs/CONTEXT.md` and relevant ADRs for this single-context repo.
