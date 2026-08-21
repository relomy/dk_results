# Per-workflow DraftKings ports

The completion workflow reads DraftKings through its own narrow `ContestResultsPort` (detail, entrants, leaderboard) rather than widening `SportProcessor`'s `DkPort`. The two workflows need different DK slices and a shared port would couple them; the cost is minor duplication if a method is ever needed by both.
