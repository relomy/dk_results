"""Shared Discord announcement chrome for the six push-notification kinds.

Every automated contest announcement — contest-warning, live, completed,
soft-finish, bonus-achievement, double-up-found — goes through one of the
``build_*`` functions here, so the visual chrome (sport emoji, header line,
bulleted detail lines, inline sheet link) is assembled once and reused. Each
builder accepts only the fields relevant to its kind; there is no shared
schema forcing empty placeholders.

``DISCORD_ROLE_MAP`` and ``SPORT_EMOJI`` live here too, alongside the chrome
that reads them, rather than staying isolated in their own modules.

Named ``discord_announcements`` rather than a ``discord/`` package: the repo's
test harness (``tests/conftest.py``) puts ``src/dk_results`` on ``sys.path``,
and a same-named ``discord`` package there would shadow the real, pip-installed
``discord.py`` library that ``bot/discord_bot.py`` imports.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dk_results.domain.contest import Contest

DEFAULT_SPORT_EMOJI = "🏟️"

SPORT_EMOJI: dict[str, str] = {
    "CFB": "🏈",
    "GOLF": "⛳",
    "LOL": "🎮",
    "MLB": "⚾",
    "MMA": "🥊",
    "NAS": "🏎️",
    "NBA": "🏀",
    "NFL": "🏈",
    "NFLAfternoon": "🏈",
    "NFLShowdown": "🏈",
    "NHL": "🏒",
    "PGAMain": "⛳",
    "PGAShowdown": "⛳",
    "PGAWeekend": "⛳",
    "SOC": "⚽",
    "TEN": "🎾",
    "USFL": "🏈",
    "XFL": "🏈",
}

# Sport -> (emoji, role mention). Also doubles as the double-up-found
# announcement's eligibility gate: a sport absent from this map gets no
# double-up announcement at all. Intentional, existing behavior.
DISCORD_ROLE_MAP: dict[str, tuple[str, str]] = {
    "NBA": (":basketball:", "<@&1034206287153594470>"),
    "CFB": (":football:", "<@&1034214536544268439>"),
    "GOLF": (":golf:", "<@&1040014001452630046>"),
    "NFLShowdown": ("<:stonks:858081117876518964>", "<@&1312478274085191770>"),
}


def sport_emoji(sport_name: str, overrides: Mapping[str, str] | None = None) -> str:
    """Return the emoji for a sport, or the default marker."""
    table = overrides if overrides is not None else SPORT_EMOJI
    return table.get(sport_name, DEFAULT_SPORT_EMOJI)


def sheet_link(spreadsheet_id: str | None, sheet_gid_map: Mapping[str, int], sheet_title: str) -> str | None:
    """Build a Discord-safe Google Sheets link, or ``None`` if not configured."""
    if not spreadsheet_id:
        return None
    gid = sheet_gid_map.get(sheet_title)
    if gid is None:
        return None
    return f"<https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={gid}>"


def _contest_url(dk_id: int) -> str:
    return f"<https://www.draftkings.com/contest/gamecenter/{dk_id}#/>"


def _header(prefix: str, sport_name: str, contest_name: str, emoji_map: Mapping[str, str] | None = None) -> str:
    return f"{prefix}: {sport_emoji(sport_name, emoji_map)} {sport_name} — {contest_name}"


def _assemble(header: str, detail_lines: Sequence[str]) -> str:
    return "\n".join([header, *(f"• {line}" for line in detail_lines)])


def build_milestone_announcement(
    *,
    prefix: str,
    sport_name: str,
    contest_name: str,
    start_date: str,
    dk_id: int,
    relative_time: str | None = None,
    sheet_link_url: str | None = None,
    emoji_map: Mapping[str, str] | None = None,
) -> str:
    """Build the shared warning/live/completed announcement text.

    ``prefix`` carries the milestone's verbatim wording (e.g. ``"Contest
    started"``); this function only supplies the shared chrome around it.
    """
    header = _header(prefix, sport_name, contest_name, emoji_map)
    relative_part = f" (⏳ {relative_time})" if relative_time else ""
    sheet_part = f"📊 Sheet: [{sport_name}]({sheet_link_url})" if sheet_link_url else "📊 Sheet: n/a"
    return _assemble(
        header,
        [
            f"🕒 {start_date}{relative_part}",
            f"🔗 DK: [{dk_id}]({_contest_url(dk_id)})",
            sheet_part,
        ],
    )


def build_soft_finish_announcement(
    *,
    sport_name: str,
    contest_name: str,
    start_date: str,
    dk_id: int,
    top_score: str,
    cashing_score: str,
    vips_cashed: Sequence[str],
    is_update: bool = False,
    relative_time: str | None = None,
    sheet_link_url: str | None = None,
    emoji_map: Mapping[str, str] | None = None,
) -> str:
    """Build the soft-finish announcement: milestone chrome plus a cash summary."""
    prefix = "Contest soft-finished (updated)" if is_update else "Contest soft-finished"
    base = build_milestone_announcement(
        prefix=prefix,
        sport_name=sport_name,
        contest_name=contest_name,
        start_date=start_date,
        dk_id=dk_id,
        relative_time=relative_time,
        sheet_link_url=sheet_link_url,
        emoji_map=emoji_map,
    )
    vip_text = ", ".join(vips_cashed) if vips_cashed else "none"
    return "\n".join(
        [
            base,
            f"• 🏆 Top score: {top_score}",
            f"• 💵 Cashing score: {cashing_score}",
            f"• ⭐ VIPs cashed (visible rows): {vip_text}",
        ]
    )


def build_bonus_achievement_announcement(sport_name: str, headline: str) -> str:
    """Build a bonus-achievement announcement: sport emoji + headline, no sheet link/entry fee."""
    return f"{sport_emoji(sport_name)} {sport_name} — {headline}"


def build_double_up_found_announcement(sport_name: str, contests: Sequence["Contest"]) -> str | None:
    """Build the double-up-found announcement for one sport's newly found contests.

    Gated: a sport absent from ``DISCORD_ROLE_MAP`` produces no announcement at
    all (``None``), preserving current, intentional scope — not every sport
    gets new-double-up alerts.
    """
    if not contests or sport_name not in DISCORD_ROLE_MAP:
        return None
    emoji, role = DISCORD_ROLE_MAP[sport_name]
    blocks = [
        _assemble(
            f"New double-up found: {sport_emoji(sport_name)} {sport_name} — {contest.name}",
            [
                f"💰 Entry: {contest.entry_fee} | Entries: {contest.entries}",
                f"🔗 DK: [{contest.id}]({_contest_url(contest.id)})",
            ],
        )
        for contest in contests
    ]
    return f"{emoji} " + "\n\n".join(blocks) + f" {role}"
