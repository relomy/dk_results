# dk_results — Architecture Context

## Vocabulary

- **Module** — any unit with an interface and implementation (function, class, package).
- **Interface** — everything a caller must know: types, invariants, error modes, ordering, config.
- **Depth** — leverage at the interface: large behaviour behind a small interface.
- **Seam** — where an interface lives; a place behaviour can be altered without editing in place.
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Leverage** — what callers get from depth (simpler call sites).
- **Locality** — what maintainers get from depth (changes concentrated in one place).
- **Draft Group Filter** — the module (`lobby/draft_group_filter.py`) that owns all sport-specific draft-group qualification logic: tag filtering, game-type constraint, suffix matching, time constraint, and NFLShowdown deduplication. Public interface: `filter_draft_groups(groups, sport) -> list[int]`.

---

## Deepening Candidates

Identified 2026-05-06. #1 and #6 done. Skipping #2.

### 1. VIP Lineup Module ← **done**

**Files:** `classes/draftkings.py`, `classes/dklineup.py`, `classes/results.py`,
`cli/db_main.py`, `services/snapshot_exporter.py`

**Problem:** The fetch-normalize-format flow for VIP lineups is duplicated across five
modules with subtle divergence. Deletion test: remove VIP handling from any one caller
and the complexity stays distributed across the other four.

**Solution:** A single deep VIP lineup module that owns the full workflow behind one small
interface. All five callers become thin delegates.

**Benefits:** Name normalization, scorecard field paths, and output format change in one
place (locality). Callers see one function call; threading and mapping are hidden
(leverage). Tests exercise the full flow through a single seam with an injected HTTP
adapter.

---

### 2. Snapshot Builder Module

**Files:** `services/snapshot_exporter.py` (~2,100 lines), `cli/db_main.py`

**Problem:** `snapshot_exporter.py` conflates four concerns: contest data collection (DB
queries + API calls), standings parsing (CSV), metric computation (ownership, salary,
cluster), and dashboard formatting. The public interface is small (`build_snapshot`) but
the implementation is untested because all concerns are tangled.

**Solution:** Split into focused sub-modules — data collection, metric aggregation,
dashboard transformation — each with its own testable interface. The public
`build_snapshot` call stays unchanged.

**Benefits:** Each sub-module is testable against fixture data (locality). The data
collection seam can be mocked for aggregation tests without hitting the DB or API
(leverage).

---

### 3. Contest Filter Seam

**Files:** `classes/contestdatabase.py`, `cli/dkcontests.py`, `lobby/double_ups.py`

**Problem:** "Find the right contest matching criteria" appears in three places with
overlapping but divergent logic — SQL fallbacks in the DB class, Python filtering in the
CLI, and a subset re-implementation in double_ups. Each carries its own edge cases.

**Solution:** A single contest-filter module owning the matching logic. DB and in-memory
callers both delegate to it.

**Benefits:** Contest-selection rules change in one place (locality). Tests exercise
criteria as pure functions with no DB or API dependency (leverage).

---

### 4. Results as a Pure Standings Parser

**Files:** `classes/results.py`, `cli/db_main.py`, `services/snapshot_exporter.py`

**Problem:** `Results` is shallow — its interface is as complex as its implementation.
It mixes CSV parsing, ownership aggregation, player normalization, and Google Sheets
formatting in one class. Callers cannot reuse the parsing step independently of the
formatting step.

**Solution:** A pure standings parser: raw rows in, `ContestStandings` data structure
out. Sheet formatting becomes a separate downstream concern.

**Benefits:** Standings parsing is testable with row fixtures and no sheet dependency
(leverage). CSV parsing, ownership tracking, and sheet formatting evolve independently
(locality).

---

### 5. Sport-Processing Module

**Files:** `cli/db_main.py` (~705 lines)

**Problem:** `db_main.py` is a 700-line orchestration script with no testable seams.
`process_sport` coordinates DB lookup, API calls, CSV fetching, Results construction,
sheet writing, VIP lineups, non-cashing stats, and train clustering in one function with
no injection points.

**Solution:** A `SportProcessor` module owning the "process one sport, write to sheet"
workflow behind a small interface. Argument parsing and sport selection remain in the CLI
entry point.

**Benefits:** `process_sport` becomes testable by injecting a fake sheet and fake DK
client (leverage). The workflow is self-contained and readable without scrolling through
700 lines (locality).

---

### 6. Draft Group Filter ← **done**

**Files:** `lobby/draft_group_filter.py` (new), `lobby/parsing.py`, `lobby/fetch.py`,
`cli/dkcontests.py`

**Problem:** `get_draft_groups_from_response` was ~170 lines with 5+ nesting levels.
It owned all "which draft groups qualify for this sport" logic — suffix matching,
game-type filtering, time-window checks, NFLShowdown deduplication — in one function
with no intermediate seams.

**Solution:** A draft group filter module that owns all sport-specific qualification
logic. NFLShowdown deduplication and suffix-matching patterns are named private
functions. Public interface: `filter_draft_groups(groups, sport) -> list[int]`.

**Benefits:** Each filtering rule is independently testable (leverage). Sport-specific
edge cases are concentrated in one module (locality). Adding a new sport's rules requires
touching one place.
