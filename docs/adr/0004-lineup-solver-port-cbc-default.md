# A swappable LineupSolver port, CBC by default, GLPK retired

The Optimizer solves for a sport's optimal lineup behind a `LineupSolver` **port**
(`solve(players, positions, salary_cap) -> list[Assignment] | None`, with
`Assignment(player_key, slot)`). No PuLP type crosses the boundary, so the LP
backend swaps without touching callers. LP construction and the solve live in the
`PulpCbcSolver` adapter in the sibling module `analytics/lineup_solver.py`;
`analytics/optimizer.py` becomes an orchestrator that pairs each returned
assignment with its `Player` in a frozen `SelectedPlayer(player, slot)`. The two
are sibling modules, not a package — `test_semantic_packages` pins them and bans a
re-exporting `__init__`.

The default backend is PuLP's **bundled CBC** (`PULP_CBC_CMD`), which needs no
external executable. This retires the previous **GLPK** backend, whose `glpsol`
binary CI never installed — leaving the optimizer's core solve path unrunnable and
untested. Retiring GLPK is done **in code only** (no dependency change), and is
what makes an end-to-end `get_optimal_lineup()` test runnable for the first time.
**HiGHS** (`highspy`) is the sanctioned next backend behind the same port, but is
not built here.

The port's `SelectedPlayer(player, slot)` representation deliberately diverges from
`parse_lineup_string` / `domain/lineup.py`, which keeps its own representation (and
its deepcopy) unchanged — out of scope here.

Fixed alongside the port: the Optimizer no longer mutates the caller's `players`
dict (the `49ers`→`FortyNiners` rename hack is deleted; LP variable names are
sanitized generically instead), no longer mutates shared `Player.pos` (the slot
rides in `SelectedPlayer`), reads the salary cap from `Sport.salary_cap` instead of
a hardcoded `50000`, and drops the dead `total_points`/`total_salary` computation.
