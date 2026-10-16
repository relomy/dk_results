# Presence rules are strict before merge and recorded, not blocking, at runtime

A snapshot field can be blank where a value belongs: no payout on a cashing row, no stats for a live player. Until now someone found it, if at all, by looking at the dashboard. The producer therefore gains **presence rules**: expectations that a field is filled in a given game state. The first three are a cashing standings row has `payout_cents`, an unlocked VIP slot has `player_key`, and an in-progress player has `stats_text` and `rt_projection`.

## Context

The hand-written validator blocks publishing on any violation. Some blanks come from DraftKings, not from producer code, and a build blocked mid-slate freezes the dashboard on a stale snapshot.

## Decision

Presence rules are strict before merge and recorded, not blocking, at runtime.

- In CI, the goldens test fails when any golden carries a presence warning, so a code bug that leaves a field blank is caught before merge.
- At runtime, a broken rule never stops a snapshot from publishing. It is recorded in the snapshot's required top-level `presence_warnings` list as a `{path, rule}` object each; the list is empty when nothing failed.
- Shape and type checks are unchanged: the pydantic contract and the hand-written validator still raise and block publishing. The build runs them first, then the presence rules.
- The rules live with the hand-written validator as a separate group that returns warnings, not violations.

## Considered options

- **Block at runtime.** One blank cell would stop the feed during a live slate.
- **Log only.** Consumers cannot see a log; the warning has to travel with the artifact.
- **Conditional rules in the dashboard.** They are truths about the data, which the producer owns under ADR-0014.

## Consequences

- Each rule needs a scenario covering its state, so the strict goldens test exercises it.
- A real-data blank surfaces through the dashboard's prod check and becomes a new scenario.
- A rule that holds for scenarios but not for real data (for example an in-progress player no tracked VIP holds carries no Scorecard facts) shows up as warnings in production rather than as a blocked build.
- `presence_warnings` is a new required field, so a consumer that allowlists top-level keys must add it.
