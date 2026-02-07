# Lobby Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `find_new_double_ups.py` into a thin orchestrator, share lobby logic in top-level `lobby/`, and migrate `dkcontests.py` to consume shared modules.

**Architecture:**
- Create `lobby/` as a top-level directory in `dk_results` repo root (sibling to `classes/` and `tests/`).
- Import as `import lobby...` (not `dk_results.lobby...`).
- Keep HTTP fetch, parsing/filtering, and formatting in `lobby/*`.
- Keep DB + `contests_state` orchestration and CLI wiring in `find_new_double_ups.py`.

**Testing Requirement:** Prefer meaningful assertions over trivial coverage-only tests; do not assert implementation details just to cover lines.

---

### Tasks
1. Add/adjust tests first for new shared module boundaries and no import-time side effects.
2. Implement `lobby/fetch.py`, `lobby/parsing.py`, `lobby/double_ups.py`, `lobby/formatting.py`, `lobby/common.py`.
3. Refactor `find_new_double_ups.py` to consume `lobby/*` and move dotenv/logging/cookies init to runtime.
4. Remove import-time logging config side effect from `classes/dksession.py`.
5. Migrate `dkcontests.py` to use shared `lobby/*` modules.
6. Consolidate temporary refactor tests into permanent test files.
7. Verify with pytest + focused coverage.
