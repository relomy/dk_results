# dk_results bonus announcements design

## Goal
Announce special bonus point opportunities for VIP lineups only, using a Discord
webhook. Initial scope covers:
- NBA: double-double (DDbl), triple-double (TDbl)
- GOLF: eagle (EAG), bogey free round (BOFR), birdie streak (BIR3+)

Announcements are deduped per contest and real player, not per VIP lineup.
Occasional duplicates from overlapping runs are acceptable.

## Integration Point
`db_main.write_players_to_sheet` after VIP lineups are fetched. This reuse of the
existing scheduler avoids a new job while limiting announcements to VIP lineups.

## Architecture
Two new modules:
- `classes/bonus_rules.py`: sport-specific parsing of `statsDescription` into
  known bonus counts.
- `classes/bonus_announcements.py`: aggregates VIP lineups, dedupes via SQLite,
  formats messages, and sends Discord webhook notifications.

Uses `dfs_common.discord.WebhookSender` with a new env var
`DISCORD_BONUS_WEBHOOK` (fallback to `DISCORD_WEBHOOK`).

## Data Flow
Skip all bonus logic if there are no VIP lineups or no webhook configured.

1. VIP lineups are fetched from DK scorecards (already in place).
2. Aggregate by normalized player name to:
   - collect VIP usernames
   - compute max bonus counts per player across VIP lineups
3. Compare against persisted `last_announced_count` in `contests.db`.
4. If `new_count > old_count`, emit one message per missing count
   (e.g., 1 -> 3 emits announcements for 2 and 3).
5. After successful sends, update `last_announced_count` with a CAS update.

Decreases (DK corrections/regressions) are ignored and documented.

## Parsing Rules
Parsing is regex-based, tolerant of punctuation/spacing, but only recognizes
known tokens to avoid false positives. `BIR3+` must be escaped to avoid matching
`BIR3` without the plus sign.

GOLF:
- `EAG`: parse counts from tokens like `2 EAG`
- `BOFR`: parse counts from tokens like `1 BOFR`
- `BIR3+`: parse counts from tokens like `2 BIR3+`

NBA:
- `DDbl` present -> count 1
- `TDbl` present -> count 1

If a token is missing, its count is 0.

## Deduplication Keys
Use `(contest_id, sport, normalized_player_name, bonus_code)`.
Normalize player names using existing `normalize_name` behavior and persist the
normalized form. Name-based keys can collide for same-name players; this risk is
accepted for now and should be documented in the code.

## SQLite Schema
Table: `bonus_announcements`

Columns:
- `contest_id` INTEGER NOT NULL
- `sport` TEXT NOT NULL
- `normalized_player_name` TEXT NOT NULL
- `bonus_code` TEXT NOT NULL
- `last_announced_count` INTEGER NOT NULL DEFAULT 0
- `updated_at` datetime NOT NULL DEFAULT (datetime('now', 'localtime'))

Constraints:
- `UNIQUE (contest_id, sport, normalized_player_name, bonus_code)`

## Concurrency and Failure Handling
Avoid holding transactions open while sending webhooks. Use an upsert to ensure
rows exist, then a compare-and-set update after successful sends:

1. Read `old_count` (default 0 if missing).
2. Send webhook messages.
3. `INSERT ... ON CONFLICT DO NOTHING` to ensure the row exists.
4. `UPDATE ... SET last_announced_count = ?, updated_at = ... WHERE
   last_announced_count = ?` and check `rowcount`.
   - If `rowcount == 0`, another run advanced the count; skip further work.
4. If webhook fails, do not update DB.
5. If DB update fails, log and continue without crashing.

This allows a small chance of duplicate announcements if two runs send before
either updates, which is acceptable for now.

## Message Formatting
Include VIP usernames sorted for deterministic messages (cap to 5, then
`+X more`).

Examples:
- NBA: `NBA: Nikola Jokic achieved a triple-double (VIPs: vip1, vip2, vip3)`
- GOLF: `GOLF: Rory McIlroy has 2 EAG (VIPs: vip1, vip2, vip3, vip4, vip5 +2 more)`
- GOLF streaks: `GOLF: Rory McIlroy has 2 BIR3+ (...)`

## Testing
Add unit tests for:
- Parsing: GOLF tokens with commas, mixed order, extra tokens, missing tokens,
  and multiple counts; include `BIR3+` and `BOFR`.
- Parsing: NBA `DDbl`/`TDbl` presence and absence in noisy strings.
- Aggregation: max-count selection across VIPs, VIP name capping to 5, and
  `+X more` formatting.
- Dedup: 1 -> 2 (single announce), 1 -> 3 (two announces), no announce when
  count does not increase.
- CAS update: simulate `rowcount == 0` to confirm skip behavior.
- Insert + CAS: ensure first-time announcements persist when the row is absent.
- Failure handling: webhook failure does not update DB; DB failure does not crash.

## Open Items / Future
- Optional cleanup of `bonus_announcements` on contest completion.
- Add stable player IDs if DK exposes them in scorecards.
