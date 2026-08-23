# Per-workflow DraftKings ports

The completion workflow reads DraftKings through its own narrow `ContestResultsPort` (detail, entrants, leaderboard) rather than widening `SportProcessor`'s `DkPort`. The two workflows need different DK slices and a shared port would couple them; the cost is minor duplication if a method is ever needed by both.

The ports are caller-facing workflow seams, not a requirement for separate concrete clients. One concrete `DraftKings` adapter may implement both ports, and the ports may have limited operation overlap where each workflow genuinely needs the operation. Port composition redesign remains out of scope; keeping the workflow interfaces separate preserves their independent contracts while the adapter keeps shared HTTP behavior local.
