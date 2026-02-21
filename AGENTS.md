# AGENTS.md

## Scope
These instructions are self-contained for this repository.
Apply them for all work under `dk_results/`.

## Repository Context
- Stack: Python
- Python: `>=3.11,<3.12`
- Package manager / runner: `uv`
- Source code: `src/`
- Tests: `tests/`
- Local dependency: `dfs-common` from `../dfs_common` (editable source)

## Working Style
- Make the smallest safe change that solves the request.
- Prefer editing existing code over adding new abstractions.
- Avoid unrelated refactors.
- Ask before changing behavior that affects public outputs or integrations.

## Preferred Commands (Enforced-Lite)
Use these defaults unless blocked by an environment issue:
1. `uv sync`
2. `uv run pytest`
3. `uv run ruff check`
4. `uv run ty check`

## Change Boundaries
- Keep edits in this repository unless the user explicitly asks for cross-repo changes.
- If a fix appears to require changes in `../dfs_common`, stop and ask first.

## Verification Before Completion
Before claiming completion:
1. Run relevant tests for touched functionality.
2. Run lint and type checks relevant to touched files.
3. Report any failing checks with exact commands and failure summaries.

## Output Expectations
In the final response, include:
1. What changed (files and behavior).
2. What commands were run.
3. What passed or failed.
4. Any follow-up risk or next step, if applicable.
