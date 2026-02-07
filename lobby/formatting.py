from classes.contest import Contest


def format_discord_messages(contests: list[Contest]) -> str:
    """Format Discord notifications for newly discovered contests."""
    return "\n".join(
        f"New dub found! [{c.start_dt:%Y-%m-%d}] Name: {c.name} ID: {c.id} "
        f"Entry Fee: {c.entry_fee} Entries: {c.entries}"
        for c in contests
    )
