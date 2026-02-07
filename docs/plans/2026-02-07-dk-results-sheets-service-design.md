# DK Results Sheets Service Design

**Date:** 2026-02-07

## Goal
Refactor dk_results Sheets wrappers to require a `SheetClient` passed in directly, removing `Sheet`/`DFSSheet` inheritance while preserving all ranges, headers, and business logic.

## Non-Goals
- No changes to sheet ranges, headers, or outputs.
- No changes to partial vs exact sheet lookup behavior.
- No new dependencies.

## Current State
`classes/dfssheet.py` defines `Sheet` and `DFSSheet` with wrapper methods around `dfs_common.sheets.SheetClient`. Callers use `DFSSheet` in `db_main.py` and `classes/dklineup.py`. Tests in `tests/classes/test_dfssheet.py` include delegation-only checks.

## Proposed Architecture
- **Domain module (`classes/dfs_sheet_domain.py`)**: pure functions for ranges and value builders (e.g., `build_values_for_vip_lineup`, `build_values_for_new_vip_lineup`, lineup range helpers). No IO.
- **Repository (`classes/dfs_sheet_repository.py`)**: wraps `SheetClient` and provides `read_range`, `write_range`, `clear_range`, and `find_sheet_id` as needed.
- **Service (`classes/dfs_sheet_service.py`)**: orchestrates reads/writes using repository + domain helpers. Replaces `Sheet`/`DFSSheet` as the public API.
- **Factory (`classes/sheets_service.py`)**: builds `SheetClient` with single-point `SPREADSHEET_ID` resolution and default credentials provider; supports injecting a fake `service` in tests.

## Data Flow
Entrypoints build a `SheetClient` via `make_sheet_client(...)`, then `DfsSheetRepository` and `DfsSheetService`. All operations (standings, lineups, headers, VIP lineups) are executed by the service using domain helpers and the same sheet ranges as today.

## Error Handling
Unchanged: missing credentials or service account file still raise from `dfs_common.sheets.service_account_provider` during client creation. Repository/service do not swallow exceptions.

## Testing Strategy
- Remove delegation-only tests from `tests/classes/test_dfssheet.py`.
- Add domain tests (pure value construction and range helpers).
- Add service tests that verify ranges and outputs using `SheetClient(service=fake)`.
- Update entrypoint tests to construct the new service or patch the factory.

## Cleanup
- Remove `classes/dfssheet.py` after all references are migrated.
