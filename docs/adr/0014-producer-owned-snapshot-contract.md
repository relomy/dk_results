# The snapshot feed's contract is producer-owned: pydantic models, goldens and a compatibility gate

The schema-3 snapshot feed is the contract between `dk_results` (producer) and
relomy/dk_dashboard (consumer). Its shape used to be described three times by
hand: the producer's validator, the producer's prose schema document
(`docs/SNAPSHOT_SCHEMA.md`) and the dashboard's TypeScript types. They drifted,
and each repo's tests passed while prod showed string ranks, padded player
names and an impossible non-cashing count (relomy/dk_results#178, #179).

We make the producer own one machine-readable contract and check every change
against it without depending on the consumer:

- **Pydantic models** in `services/snapshot_v3/models/` define the envelope and
  validate every snapshot the feed builds. This extends ADR-0003: pydantic also
  defines the outbound snapshot contract, still only at a boundary, still
  confined to `dk_results`; domain objects stay plain.
- **The exported JSON Schema** (`contract/snapshot.schema.json`) is generated
  from the models and committed; a test fails while it is stale. It is the
  authority on shape; the schema document explains meaning, units and
  omission rules.
- **Golden envelopes** (`contract/goldens/`) are complete snapshots the real
  pipeline builds from fixed scenarios, so every shape change shows up as a
  reviewable diff.
- **A compatibility gate** in CI compares the PR's exported schema with the
  base branch's. Additive changes pass. A breaking change (a declared field
  removed or renamed, a type changed or narrowed, a constraint tightened or
  added, a union branch dropped, an optional field made required, a required
  field made optional, an enum value removed) fails unless the PR is labeled
  `breaking-change` and the schema document's Breaking changes log gains an
  entry. The gate guards only what the previous schema declared: declaring a
  loose placeholder section's fields is not breaking, because the placeholder
  promised nothing a consumer could build on. Required-to-optional goes beyond
  the original spec's list: the dashboard generates TypeScript types from the
  schema, and `x: T` becoming `x?: T` breaks them. Regex containment is
  undecidable, so a new or changed `pattern` counts as narrowing.
- **The consumer checks itself.** The dashboard pulls the exported schema and
  goldens at a pinned commit, generates its types from them, and runs its own
  contract test. Producer CI never runs consumer code.

Producer CI doesn't run the consumer's tests because the producer owns the
contract: a consumer bug or flaky test must never block a producer merge. None
of the bugs that prompted this was the producer breaking a working consumer;
they were wrong values, unread additions and consumer-side bugs. The real
producer-side risk is an accidental breaking change, and the gate covers it
using only the producer's own artifacts.

Known gap: the gate compares shapes, not meaning. A field that keeps its name
and type but changes meaning passes; the schema document's prose and the
golden diffs, read by a reviewer, guard that.

Rejected alternatives:

- **Hand-maintained validator and prose as the contract.** This is what
  drifted. Hand-written checks allow whatever they don't think to reject (a
  string where the consumer needs a number), and prose can't be checked.
- **Consumer tests in producer CI.** It couples producer merges to the
  consumer's code, its bugs and its flakiness, and needs the consumer's
  repository at build time, while protecting against a failure mode that
  didn't occur.
- **Scheduled prod monitoring as the primary defence.** It finds a broken
  snapshot only after it is published and the dashboard has read it. It may
  supplement the gate later, but it can't stop a bad change from merging.
