"""Shared builders for ContestDatabase persistence tests."""

from dk_results.persistence.contestdatabase import ContestDatabase


def insert_contest(
    db: ContestDatabase,
    *,
    dk_id: int,
    sport: str = "NBA",
    name: str = "Contest",
    start_date: str = "2024-01-01 00:00:00",
    draft_group: int = 1,
    total_prizes: int = 1000,
    entries: int = 100,
    positions_paid: int | None = None,
    entry_fee: int = 25,
    entry_count: int = 0,
    max_entry_count: int = 1,
    completed: int = 0,
    status: str | None = "LIVE",
) -> None:
    db.conn.execute(
        "INSERT INTO contests "
        "(dk_id, sport, name, start_date, draft_group, total_prizes, entries, positions_paid, entry_fee, "
        "entry_count, max_entry_count, completed, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            dk_id,
            sport,
            name,
            start_date,
            draft_group,
            total_prizes,
            entries,
            positions_paid,
            entry_fee,
            entry_count,
            max_entry_count,
            completed,
            status,
        ),
    )
    db.conn.commit()
