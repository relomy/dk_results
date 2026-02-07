# DK Results Sheets Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `classes/dfssheet.py` with a repository + domain + `DfsSheetService` that requires a `SheetClient` passed in directly, preserving all ranges, headers, and business logic.

**Architecture:** Add a pure domain module for ranges/value building, a repository around `SheetClient`, and a service that orchestrates reads/writes. Entry points use a `sheets_service.make_sheet_client()` factory. Remove `classes/dfssheet.py` and delegation tests after migration.

**Tech Stack:** Python, pytest, dfs_common.sheets

---

### Task 1: Add domain helpers for ranges and lineup value building

**Files:**
- Create: `classes/dfs_sheet_domain.py`
- Test: `tests/classes/test_dfs_sheet_domain.py`

**Step 1: Write the failing test**

Create `tests/classes/test_dfs_sheet_domain.py` covering:
- `end_col_for_sport` returns `E` for GOLF/PGA, `H` otherwise
- `data_range_for_sport` and `header_range_for_sport` match current output
- `lineup_range_for_sport` and `new_lineup_range_for_sport` mirror `get_lineup_range` and `get_new_lineup_range`
- `build_values_for_vip_lineup` and `build_values_for_new_vip_lineup` reproduce existing outputs

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/classes/test_dfs_sheet_domain.py -v`
Expected: FAIL (module/functions missing)

**Step 3: Write minimal implementation**

Implement `classes/dfs_sheet_domain.py`:
- Copy existing lineup range constants and value-building logic from `classes/dfssheet.py` and `classes/sport.py`.
- Keep outputs identical.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/classes/test_dfs_sheet_domain.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add classes/dfs_sheet_domain.py tests/classes/test_dfs_sheet_domain.py
git commit -m "feat: add dk_results sheet domain helpers"
```

---

### Task 2: Add repository + service and update entrypoints

**Files:**
- Create: `classes/dfs_sheet_repository.py`
- Create: `classes/dfs_sheet_service.py`
- Create: `classes/sheets_service.py`
- Modify: `db_main.py`
- Modify: `classes/dklineup.py`
- Modify: `generate_sheet_gids.py`
- Test: `tests/classes/test_dfs_sheet_service.py`

**Step 1: Write the failing test**

Create `tests/classes/test_dfs_sheet_service.py`:
- Use `SheetClient(service=fake)` with a fake service to capture ranges.
- Verify `clear_standings`, `clear_lineups`, `write_players`, `write_columns`, `write_lineup_range`, `add_last_updated`, `add_contest_details`, `add_min_cash`, `add_non_cashing_info`, `add_train_info`, and `get_lineup_values` use the same ranges as before.
- Verify `write_vip_lineups` and `write_new_vip_lineups` preserve value shapes and ranges.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/classes/test_dfs_sheet_service.py -v`
Expected: FAIL (modules missing)

**Step 3: Write minimal implementation**

Implement:
- `classes/dfs_sheet_repository.py` with `read_range`, `write_range`, `clear_range`, and `find_sheet_id` if needed.
- `classes/dfs_sheet_service.py` with methods mirroring `DFSSheet` behavior, calling domain helpers.
- `classes/sheets_service.py` with `make_sheet_client` resolving `SPREADSHEET_ID` and using `service_account_provider` when no service injected.
- Update `db_main.py`, `classes/dklineup.py`, and `generate_sheet_gids.py` to use the new service + factory.

**Step 4: Run test to verify pass**

Run: `uv run pytest tests/classes/test_dfs_sheet_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add classes/dfs_sheet_repository.py classes/dfs_sheet_service.py classes/sheets_service.py db_main.py classes/dklineup.py generate_sheet_gids.py tests/classes/test_dfs_sheet_service.py
git commit -m "feat: add dk_results sheet repository and service"
```

---

### Task 3: Remove legacy dfssheet and update tests

**Files:**
- Delete: `classes/dfssheet.py`
- Modify: `tests/classes/test_dfssheet.py`
- Modify: docs referencing dfssheet

**Step 1: Write the failing tests**

Update tests to use `DfsSheetService` and domain helpers. Remove delegation-only tests that assert wrapper calls.

**Step 2: Run tests to verify failures**

Run: `uv run pytest -v`
Expected: FAIL due to removed module imports

**Step 3: Implement minimal changes**

- Remove `classes/dfssheet.py` and update imports.
- Update or replace `tests/classes/test_dfssheet.py` with service/domain tests.
- Update docs referencing `dfssheet`.

**Step 4: Run full test suite**

Run: `uv run pytest`
Expected: PASS

**Step 5: Commit**

```bash
git add classes tests docs
git commit -m "refactor: replace dfssheet with repository/service"
```

---

### Task 4: Final verification

**Files:**
- Test: `tests/`

**Step 1: Run full test suite**

Run: `uv run pytest`
Expected: PASS

**Step 2: Commit (if needed)**

If fixes were required:

```bash
git add classes tests docs
git commit -m "fix: stabilize dk_results sheet service refactor"
```
