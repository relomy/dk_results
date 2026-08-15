# Lineup Slot Validation Design

## Goal

Make lineup parsing preserve the domain distinction between known players, valid locked slots, and invalid unresolved player references.

## Domain rules

- A `Lineup` contains roster slots for one sport variant.
- A resolved slot refers to a known `Player` from the contest player set.
- A `LOCKED` slot is valid even though DraftKings has not exposed the player's identity yet.
- Any other unresolved player reference is invalid.
- Invalid lineups must not be returned as partial lineups.

## Design

`Lineup` will expose slots whose values are either a resolved `Player` or an explicit `LockedSlot`. The parser will retain the roster position for locked slots. When a non-locked name is absent from the player set, it will raise a dedicated `LineupParseError` containing the unresolved name and roster position.

Existing callers that operate on player attributes will handle locked slots explicitly. No unrelated changes to standings, salary accounting, or contest parsing are included.

## Error boundary

The parser is responsible for enforcing the invariant and failing clearly. Higher-level ingestion code may decide whether to skip an invalid standings entry or reject the surrounding contest, but it must not receive a silently truncated lineup.

## Tests

- Known players continue to parse and sort by sport roster order.
- Locked slots parse as explicit locked values and retain their positions.
- Unknown player names raise `LineupParseError`.
- A lineup containing both valid and invalid references does not return a partial result.
- Existing lineup and standings behavior remains green.
