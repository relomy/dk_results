# dk_results

The language of DraftKings contest tracking: slates and players, contests and
their standings, lineups, and the announcements and snapshot feed built from
them. Module interfaces live in `docs/MODULES.md`; decisions in `docs/adr/`.

## Language

### Slate and players

**Player**:
An athlete available for selection in a contest slate, with a sport position, salary, and contest performance data.

**Competition**:
One real-world game or event in a draft group, as DraftKings models it, with a home team, an away team and a start time. Golf has a single Competition, the tournament, with no opponent.

**Matchup**:
A player's opponent in their Competition, relative to the player's team ("vs. X" at home, "at X" away). It stays the same for the whole slate. A Competition with no opponent has no Matchup.

**Game status**:
The current state of a player's Competition (pre-game, in progress, finished). In the Google Sheet's Matchup column it replaces the matchup once the game starts, and the sheet's conditional formatting depends on that. A paused game (Delayed, Suspended) is still *in progress*; a game moved off the slate or called off (Postponed, Cancelled) counts as *finished*, alongside Final. A **locked** slot (a player DraftKings hides until their game starts) is always *pre-game*: remaining, never in play or finished. Golf players carry no Game status at all (only the tournament name), so golf has no ownership remaining or ownership in play.
_Avoid_: "game info". That's DraftKings' raw salary-CSV column: it holds a Matchup before the game and a Game status after.

**User**:
A named contest participant represented in standings, associated with one submitted lineup.

**Lineup**:
A user's roster of player assignments for a sport variant. Each slot is either associated with a known `Player` or is explicitly locked before that player's identity is available (DraftKings hides another user's player until that player's game starts, so a locked slot carries no name, salary or ownership); an ordinary unresolved player reference makes the lineup invalid.

**Scorecard**:
DraftKings' per-entry roster readout (`/scores/v2/entries/{draft group}/{entry key}`): one row per roster slot, each carrying the player's live points, stats summary, real-time projection, value icon and time remaining, plus the player's `draftableId`. Fetched per tracked VIP. The slot's identity (which entry holds it) is the entry's; every other field is a fact about the player and is the same whichever entry holds them. A locked slot carries no player facts.
_Avoid_: treating its per-player fields as lineup facts.

**PMR**:
Players minutes remaining: the game minutes left across a lineup's players. At lineup level it is a sum (a VIP's `pmr` in standings); on one scorecard row it is that single player's minutes remaining, with `timeRemainingUnit: "PMR"`. Zero means the player's game is finished.
_Avoid_: **Game status** (the state of the Competition, not minutes).

### Lobby and draft groups

**Lobby feed**:
The anonymous DraftKings lobby payloads for a sport: upcoming contests with their draft groups, and in-progress contests. Read without authentication (ADR-0009). Distinct from `ContestResultsPort` (authenticated, one contest's live readouts).
_Avoid_: lobby row (that is a single `Contest`).

**Contest**:
The parsed DraftKings *lobby row*: a frozen, read-only value validated once at the DraftKings-payload boundary and then flowed inward unchanged. Module: `domain/contest.py`.
_Avoid_: ContestStandings (parsed salary/standings CSVs, not the lobby row); ContestDatabase (stored SQLite contest rows, not the lobby DTO).

**Draft Group Filter**:
The single owner of the sport-specific rules for which draft groups a sport plays: tag, game type, suffix, start window, and NFLShowdown deduplication. Module: `lobby/draft_group_filter.py`; see ADR-0012, ADR-0013 and ADR-0017.

**Featured draft group**:
A raw DraftKings draft group whose `DraftGroupTag` is exactly `Featured`.

**Featured Showdown**:
A **Featured draft group** whose game type is Showdown. It is one **Competition**, a single game, so it is never a multi-game slate. DraftKings tags one per game window.

**Start window**:
A half-open time-of-day range `[start, end)` in ET that a sport accepts for a draft group's start. A sport may have several windows; a sport with none accepts any start time. See ADR-0017.

**Start-time bucket**:
A group of lobby contests sharing a calendar date and the same displayed local start time at `HH:MM` precision. Used by the `dkcontests` report to distinguish same-day slates without changing contest selection or persistence behavior.

### Standings and cashing

**ContestStandings**:
The data structure produced by parsing a DraftKings contest's salary and standings CSVs. Owns players, users, VIP list, cash line, and non-cashing stats. Contest metadata (`contest_id`, `name`) stays with callers. Module: `domain/contest_standings.py`.

**Remaining salary**:
The salary cap minus the salaries of a lineup's revealed players. DraftKings reveals a player when their game starts, so mid-slate this is the unspent budget *plus* the salary of players who haven't started yet (mostly the latter); once every game has started it is exactly the unspent budget. Part of the `User` domain state.
_Avoid_: reading it as unspent money mid-slate, or as all salary still to play (in-progress players are already subtracted); **Average salary remaining** (a contest-level figure over unfinished slots).

**Cashing**:
An entry has a positive realized payout. The availability of payout data is a separate fact and does not by itself mean the entry is cashing. Payout is decoded in one place. Module: `draftkings/leaderboard.py`.

**Cash line**:
The last paid position and its score in a contest's standings. A positional/scoring cutoff, not a realized-payout fact. Owned by `ContestStandings`; see ADR-0011.
_Avoid_: conflating with **Cashing** — the cash line only tells you where the cutoff sits, not whether a given entry's payout is confirmed.

**Projected cashing**:
A tracked VIP's standings row sits at or above the current **cash line** (`rank <= cash line rank`), as of the last `SportProcessor` poll. A provisional estimate shown in the bot's `!live` command, computed at read time. Distinct from **Cashing**, the realized-payout fact. See ADR-0011.

**VipCashStatus**:
One tracked VIP's own standings row (name, rank, points) in one contest, as of the last poll. See ADR-0011.

**Non-cashing**:
A standings row ranked below the **cash line** (`rank > positions_paid`), as of the last standings parse. Decided by rank alone: rows tied with, or scoring above, the cash line's score but inside the paid positions are never non-cashing. A positional fact, the counterpart of the cash line; it is *not* the negation of **Cashing** (an entry can be non-cashing without any payout data existing).
_Avoid_: "not cashing" as a payout claim.

**Ownership remaining**:
The summed ownership of an entry's players whose games are not finished (see **Game status**). Pre-game and in-progress players both count.

**Field remaining**:
The mean **ownership remaining** across every entry in a contest's standings. The baseline a VIP's ownership remaining is compared against.
_Avoid_: watchlist total (the mean over the top-remaining-ownership subset, biased upward).

**Ownership in play**:
The summed ownership of a VIP's players whose games are in progress, including paused (Delayed, Suspended) games. Excludes pre-game and finished players, which is what distinguishes it from **ownership remaining**.

**Uniqueness delta**:
**Field remaining** minus a VIP's own **ownership remaining**. Positive means the VIP's still-live players are less owned than the field's, so the VIP is more unique.

**Average salary remaining**:
The mean salary of every unfinished lineup slot whose player is known, across all entries in a contest, weighted by slot. Locked slots are left out because their salary is hidden. A contest-level figure, not per VIP.
_Avoid_: **Remaining salary** (one user's cap minus their revealed players' salaries).

### Sheets

**Format plan**:
The cell number formats a values-builder returns alongside the value grid it lays out, written together with the values and reasserted on every write, so the sheet's formatting heals itself instead of depending on formatting set once by hand. Modules: `domain/dfs_sheet_domain.py`, `domain/contest_standings.py`.
_Avoid_: applying a `NumberFormat` via a second, separate write call — the point of the pattern is a single combined values+format write.

### Lineup optimization

**Optimizer**:
The orchestrator that solves for a single sport's optimal lineup behind a swappable **LineupSolver**. Module: `analytics/optimizer.py`.

**LineupSolver**:
The port the Optimizer solves behind, keeping the LP backend swappable; the default adapter is PuLP's bundled CBC. See ADR-0004. Module: `analytics/lineup_solver.py`.

**Roster slot**:
One fillable position in a lineup. `Sport.positions` enumerates every slot with its multiplicity (NFL lists `RB` twice, Golf lists `G` six times) and is the **sole source of truth** for a lineup's required composition and size. A player may fill a slot only if that slot appears in the player's `roster_pos` — DraftKings' per-player slot eligibility; flex slots (`FLEX`, `G`, `F`, `UTIL`, `S-FLEX`) are ordinary slots. See ADR-0005.
_Avoid_: min/max position ranges (`positions_count` / `position_constraints` — an abandoned alternative model, retired in ADR-0005).

**Optimizer eligibility**:
Whether a sport's lineups are optimized (`Sport.allow_optimizer`). Opt-in: a sport is optimized only once its `positions` layout is confirmed against real DraftKings data, so an unverified sport never silently ships a wrong lineup. See ADR-0005.

### Workflows and storage

**SportProcessor**:
The workflow that processes one live sport: parse its contest's standings, write them to the sheet, announce bonuses, and record the **cash line**. Module: `sport_processor.py`.

**ContestDatabase**:
The single boundary for reading and writing contest rows in SQLite (live, upcoming, incomplete, and completion state). Module: `persistence/contestdatabase.py`.
_Avoid_: NotificationStore (owns notification/presence rows, not contests); ContestResultsPort (live DraftKings readouts, not stored rows).

**ContestRow**:
The named, frozen shape of one contest read by ID, from `ContestDatabase` or from a DraftKings contest detail. See ADR-0006.

### Runtime configuration

**Runtime bootstrap**:
The one startup operation each executable performs: load the repository `.env` without overriding a non-empty process value, resolve repository configuration, and apply values only where the process environment is unset or empty. Library imports do not perform it. Module: `config.py`; see ADR-0009 (runtime bootstrap).
_Avoid_: the redundant `dotenv` package; per-entry-point dotenv setup; import-time configuration.

### Contest completion & notifications

**CompletionProcessor**:
The workflow that advances each tracked contest and announces its milestones (warning, live, completed, soft-finish), and owns when a milestone announcement is suppressed (ADR-0008). Module: `completion_processor.py`.

**Notification event**:
The identity of a single announcement about a contest, used to keep announcing idempotent. One per milestone: starting-soon warning, live, completed, soft-finish.

**NotificationStore**:
Persistence that keeps a milestone from being announced twice, and caches VIP presence. Module: `persistence/notification_store.py`.
_Avoid_: ContestDatabase (owns contest rows, not notifications).

**Warning schedule**:
The per-sport list of "minutes before start" at which a starting-soon warning fires, with a default.
_Avoid_: cron interval (schedules the run itself, not the warning).

**Soft-finish**:
The state where a live contest's scoring is effectively final though DraftKings has not marked it COMPLETED; triggers a VIP-cash summary.
_Avoid_: completed / CANCELLED (DraftKings' own terminal statuses).

**VipPresence**:
The oracle answering whether a tracked VIP is entered in a contest, returning a presence verdict. Short-circuits at the first tracked VIP found; never enumerates the full entrant list, so it proves presence/absence but not the complete roster of who's in. Module: `notifications/vip_presence.py`.

**Presence verdict**:
A VipPresence result: `present`, `absent`, `unknown`, or `unknown_capped`. `unknown_capped` is a structural variant of `unknown` — the entrant-page cap was hit before a conclusive read, because the field is too large to fully scan, not because of a transient failure. Which verdicts suppress an announcement differs by milestone; see ADR-0008.

**ContestResultsPort**:
The seam through which the completion workflow reads one contest's live DraftKings readouts — state, entrants, leaderboard — by `dk_id`.
_Avoid_: Lobby feed (the anonymous per-sport listing of new contests); stored contest state (`ContestDatabase.get_contest_state`).

**Announcement**:
The shared visual chrome (sport emoji, header line, bulleted detail lines, inline sheet link) every push notification, and the `!contests`/`!live` bot commands, render through. Module: `discord_announcements.py`. See ADR-0010.
_Avoid_: Notification event (the dedup identity, not the message text).

### Snapshot feed to the dashboard

**Snapshot feed**:
The scheduled job that publishes snapshot artifacts to the object store the dashboard reads, each cycle running build → publish → load. Module: `snapshot_feed.py`; see ADR-0007.

**Snapshot artifact**:
The canonical schema-3 multi-sport JSON envelope produced for downstream consumers. Rollback restores a known-good artifact or producer version; it does not require runtime compatibility with retired schemas.

**Snapshot collector**:
The collect step of the snapshot pipeline: resolves one contest and gathers its DraftKings and `ContestDatabase` data into one frozen bundle for derive and build. Module: `services/snapshot_v3/collector.py`.

**Object store**:
The keyed JSON store the feed loads into and the dashboard reads from. Modules: `feed/object_store.py`, `feed/r2.py`.
_Avoid_: `wrangler` (rejected in ADR-0007); the dashboard's HTTP API (a separate read edge — the feed writes object keys, not `/api/*`).

**Latest pointer**:
`latest.json`, naming the current snapshot key plus the today/yesterday manifest paths. It only ever names a snapshot already in the object store.

**Day manifest**:
`manifest/<date>.json`, the list of one UTC day's snapshots, kept in the object store.
_Avoid_: local snapshot state on the Pi (there is none — the object store is the source of truth).

**Producer commit**:
The dk_results commit that built a snapshot artifact, or unknown when it cannot be told (such as a checkout with uncommitted changes).
_Avoid_: producer version, build ID.

**Completed at**:
The UTC moment the producer first observed DraftKings reporting a contest `COMPLETED`; it never changes afterwards. An observation time, not DraftKings' real end time, and unset for contests that are not completed, cancelled contests, and contests completed before it was recorded. A contest in the snapshot feed carries it only once completed.
_Avoid_: end time, finished at (they suggest DraftKings' own clock); the snapshot's `generated_at`.

**Completion window**:
How long after its completed at a completed contest stays in the snapshot feed for a sport with no live contest, so the **Final standings** remain landable. A live contest in the same sport replaces it immediately.

**Presence rule**:
An expectation that a snapshot field is filled, always or in a given game state (a cashing row has a payout; an in-progress player has stats). Strict before merge (the goldens test fails on any warning); never blocks publishing a live snapshot.
_Avoid_: required field (the schema's term), null check.

**Presence warning**:
A presence rule a published snapshot artifact broke, recorded in the artifact itself.
_Avoid_: validation error (those block publishing).
