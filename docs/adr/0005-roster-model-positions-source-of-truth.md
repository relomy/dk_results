# `Sport.positions` is the sole source of truth for roster composition

The optimizer fills exactly one player per slot listed in `Sport.positions`,
matching each slot against DraftKings' per-player `roster_pos` eligibility.
`positions` therefore must enumerate every roster slot with its true
multiplicity — NFL lists `RB` twice, Golf lists `G` six times, MLB lists `P`
twice and `OF` three times. This fixes issue #62, where slots whose real count
differed from `positions.count(slot)` under-filled (Golf 1/6, MLB 7/10, NHL 5/9)
or went infeasible (XFL/USFL) — silently, because the short lineup was written
to the sheet with no error.

## Rejected alternative — min/max `position_constraints`

A `(position, min, max)` + `positions_count` model was half-built (declared on
`CFBSport`/`GolfSport`, commented on NFL/NBA) but never read by the solver. It is
both more complex and *less* correct: per-position ranges plus a total do not
enforce flex-tier grouping. For NBA's `PG, SG, SF, PF, C, G, F, UTIL`, ranges of
1–2 per base position with a total of 8 admit `2 PG, 2 SG, 2 C, 1 SF, 1 PF` —
which leaves no forward for the `F` slot, an invalid DraftKings lineup. The
enumerate-slots model rejects that for free, because DraftKings already encodes
flex/`G`/`F`/`UTIL`/`S-FLEX` eligibility in each player's `roster_pos`, which the
solver consumes directly. `positions_count` and `position_constraints` are
removed.

## `allow_optimizer` now defaults to `False` (opt-in)

A sport is optimized only once its `positions` layout is confirmed against a real
DraftKings salary/standings file, so an unverified sport cannot silently ship a
wrong lineup. Enabled at introduction, from confirmed layouts: **NFL, NBA, MLB,
SOC, CFB, GOLF, WeekendGolf**. Everything else — NHL, NASCAR, Tennis, MMA, LOL,
the PGA variants, all Showdown variants, and XFL/USFL — stays off until confirmed.

**Showdown is confirmed but still gated.** NFL Showdown's layout is known from a
real file (1 `CPT` + 5 `FLEX`), and `positions` records it, but the `CPT` slot
scores and costs 1.5x. The flat per-player solver applies one `fpts`/`salary`
regardless of slot, so it would fill a size-correct lineup that misvalues the
captain. Correct showdown optimization needs a captain-multiplier model — a
separate enhancement — so `allow_optimizer` stays off. Size-correctness is not
value-correctness here, so showdown is deliberately excluded from the roster-size
acceptance test.

XFL and USFL are a specific hazard: they author a `WR/TE` compound slot, but
`Player.roster_pos = roster_pos_raw.split("/")` would split a real `WR/TE`
eligibility token into `["WR", "TE"]` (the same `/` also separates genuine
multi-eligibility like `RB/FLEX`, so the splitter can't simply stop). Resolving
that needs a real XFL/USFL salary file to see the true vocabulary; until then
they stay gated and the splitter is left unchanged.

## Post-solve guard

`Optimizer.get_optimal_lineup` validates `len(lineup) == len(positions)` before
returning, and logs distinctly for an infeasible solve versus a short (roster
misconfiguration) one — so a wrong-size lineup is discarded and surfaced rather
than written.
