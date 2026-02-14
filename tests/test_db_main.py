import datetime
from argparse import Namespace
from pathlib import Path

import db_main
from classes.sport import NFLSport


def _salary_csv_text() -> str:
    return (
        "Position,ID,Name,ID2,Roster Position,Salary,Game Info,TeamAbbrev,AvgPoints\n"
        "QB,,Tom Brady,,QB,7000,NE@NYJ 1:00PM ET,NE,0\n"
        "RB,,Derrick Henry,,RB/FLEX,8000,TEN@IND 1:00PM ET,TEN,0\n"
    )


def _standings_rows() -> list[list[str]]:
    return [
        ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup", "", "Player", "Roster Position", "%Drafted", "FPTS"],
        [
            "1",
            "111",
            "UserA",
            "0",
            "120",
            "QB Tom Brady RB Derrick Henry",
            "",
            "",
            "",
            "",
            "",
        ],
        ["", "", "", "", "", "", "", "Tom Brady", "QB", "50.00%", "20"],
        ["", "", "", "", "", "", "", "", "", "", ""],
    ]


class _FakeContestDb:
    def get_live_contest(self, *_args, **_kwargs):
        return (
            123,
            "Test Contest",
            999,
            1,
            "2026-02-14 01:00:00",
        )


class _FakeDraftkings:
    def download_salary_csv(self, _sport: str, _draft_group: int, filename: str) -> None:
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_salary_csv_text(), encoding="utf-8")

    def download_contest_rows(self, *_args, **_kwargs):
        return _standings_rows()

    def get_vip_lineups(self, *_args, **_kwargs):
        return []


class _FakeSheet:
    def __init__(self):
        self.players = []

    def clear_standings(self):
        return None

    def write_players(self, values):
        self.players = list(values)

    def add_contest_details(self, *_args, **_kwargs):
        return None

    def add_last_updated(self, *_args, **_kwargs):
        return None

    def add_min_cash(self, *_args, **_kwargs):
        return None

    def clear_lineups(self):
        return None

    def write_vip_lineups(self, *_args, **_kwargs):
        return None

    def add_non_cashing_info(self, *_args, **_kwargs):
        return None

    def add_train_info(self, *_args, **_kwargs):
        return None

    def add_optimal_lineup(self, *_args, **_kwargs):
        return None


def test_process_sport_parses_player_stats_only_rows_and_skips_blank_users(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db_main, "Draftkings", _FakeDraftkings)
    fake_sheet = _FakeSheet()
    monkeypatch.setattr(db_main, "build_dfs_sheet_service", lambda _sport: fake_sheet)
    monkeypatch.setattr(db_main, "load_vips", lambda: [])

    observed = {}

    def _capture_train(_sheet, results):
        observed["users"] = len(results.users)

    monkeypatch.setattr(db_main, "write_train_info", _capture_train)

    args = Namespace(nolineups=False)
    db_main.process_sport(
        "NFL",
        {"NFL": NFLSport},
        _FakeContestDb(),
        datetime.datetime(2026, 2, 14, 12, 0, 0),
        args,
        [],
    )

    # Player-only standings row should update ownership/fpts, so Tom Brady appears in player output.
    assert any(row[1] == "Tom Brady" for row in fake_sheet.players)
    # Blank core row should not create phantom users in db_main path.
    assert observed["users"] == 1
