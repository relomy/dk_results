# VipPresence consults the standings poll before the entrant-page scan

`VipPresence` answered "is *any* tracked VIP entered?" only by an authenticated, paginated entrant scan: a DraftKings call per check, and `unknown_capped` on the largest fields. `SportProcessor` already parses the full standings CSV every poll and persists the cash line and `VipCashStatus` rows (ADR-0011).

## Decision

`VipPresence.verdict()` consults the persisted standings poll after the cache and before the entrant scan, through a narrow `StandingsPresencePort` (`get_standings_cash_snapshot`) that `ContestDatabase` satisfies structurally. The read returns the cash line and VIP rows from one poll, as required by ADR-0011; it must not read those facts separately.

- A poll is *usable* only when the persisted cash line has a rank. `SportProcessor` clears VIP rows until a cash line exists (spec #138), so empty rows before that point are not evidence of absence. An unusable poll falls through to the entrant scan unchanged.
- A usable poll with a tracked VIP is `present` and cached (a cached `present` is permanent). A usable poll without one is `absent` and **not** cached, so it never collides with the entrant scan's `VIP_ABSENT_REFRESH_MINUTES` policy.
- `present_vips(dk_id, vip_names)` returns the names the last poll found, `[]` when unusable. Nothing consumes it yet.
- `verdict()`'s signature and values are unchanged, so the ADR-0008 suppression policies are untouched.

## Considered options

- **A `standings_polled_at` column stamped by `SportProcessor`** (the original spec). It would also resolve polled-before-cash-line contests, but those rows are cleared, so it would report a false `absent`. Deriving usability from the snapshot cash line needs no additional schema change or timestamp write.

## Consequences

- The snapshot API keeps presence outcomes coherent across concurrent polls.
- A contest polled before any cashing user exists still pays for the entrant scan.
