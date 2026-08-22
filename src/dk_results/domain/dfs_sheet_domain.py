"""Pure helpers for DFS sheet ranges and value formatting."""

from typing import Any

from .sport import get_lineup_range

START_COL = "A"


def end_col_for_sport(sport: str) -> str:
    if "PGA" in sport or sport == "GOLF":
        return "E"
    return "H"


def data_range_for_sport(sport: str) -> str:
    end_col = end_col_for_sport(sport)
    return f"{sport}!{START_COL}2:{end_col}"


def header_range_for_sport(sport: str) -> str:
    end_col = end_col_for_sport(sport)
    return f"{sport}!{START_COL}1:{end_col}1"


def lineup_range_for_sport(sport: str) -> str:
    lineup_range = get_lineup_range(sport)
    if not lineup_range:
        raise KeyError(f"Missing lineup range for sport '{sport}'")
    return f"{sport}!{lineup_range}"


def build_values_for_vip_lineup(user: dict[str, Any], players: list[dict[str, Any]]) -> list[list[Any]]:
    values: list[list[Any]] = [[user["user"], None, "PMR", user["pmr"], None, None, None, None]]
    values.append(["Pos", "Name", "Own", "Salary", "Pts", "Value", "RT Proj", "Time", "Stats"])
    for player in players:
        name = player.get("name", "") or ""
        value_icon = player.get("valueIcon")
        if value_icon == "fire":
            name += " 🔥"
        elif value_icon == "ice":
            name += " ❄️"
        values.append(
            [
                player.get("pos", ""),
                name,
                player.get("ownership", ""),
                player.get("salary", ""),
                player.get("pts", ""),
                player.get("value", ""),
                player.get("rtProj", ""),
                player.get("timeStatus", ""),
                player.get("stats", ""),
            ]
        )
    values.append(
        [
            "rank",
            user.get("rank", ""),
            None,
            user.get("salary", ""),
            user.get("pts", ""),
            None,
            None,
            None,
        ]
    )
    return values
