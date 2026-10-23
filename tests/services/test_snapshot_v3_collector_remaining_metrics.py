"""Remaining and leverage metrics from a parsed standings CSV and salary file."""

import csv
from typing import Any

import pytest

from dk_results.domain.contest_standings import ContestStandings
from dk_results.domain.lineup import Lineup
from dk_results.domain.player import Player
from dk_results.domain.user import User
from dk_results.persistence.contestdatabase import ContestRow
from dk_results.services.snapshot_v3 import collector
from dk_results.services.snapshot_v3.collector import collect_snapshot
from dk_results.services.snapshot_v3.pipeline import build_snapshot_v3_envelope
from dk_results.vip_lineups import VipLineup
from tests.services.snapshot_v3_collector_fakes import _FakeContestDB, _FakeDK


class _RemainingMetricsDK(_FakeDK):
    def __init__(self, statuses):
        super().__init__(
            standings_rows=[
                ["rank", "entry", "name", "pmr", "points", "lineup", "", "player", "position", "ownership", "fpts"],
                [
                    "1",
                    "e1",
                    "leader",
                    "0",
                    "150",
                    "PG Alpha SG Bravo SF Charlie PF Delta C Echo G LOCKED F LOCKED UTIL LOCKED",
                ],
                [
                    "2",
                    "e2",
                    "chaser",
                    "100",
                    "100",
                    "PG Alpha SG Bravo SF Charlie PF Delta C Echo G Foxtrot F LOCKED UTIL LOCKED",
                ],
                ["", "", "", "", "", "", "", "Alpha", "PG", "20%", "10"],
                ["", "", "", "", "", "", "", "Bravo", "SG", "10%", "10"],
                ["", "", "", "", "", "", "", "Charlie", "SF", "30%", "10"],
                ["", "", "", "", "", "", "", "Delta", "PF", "40%", "10"],
                ["", "", "", "", "", "", "", "Echo", "C", "50%", "10"],
                ["", "", "", "", "", "", "", "Foxtrot", "G", "15%", "10"],
            ]
        )
        self.statuses = [*statuses, statuses[1]]

    def download_salary_csv(self, _name, _draft_group, path):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Position", "Name", "Roster Position", "Salary", "Game Info", "TeamAbbrev"])
            for name, pos, salary, status in zip(
                ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"),
                ("PG", "SG", "SF", "PF", "C", "G"),
                (9000, 8000, 7000, 6000, 5000, 4000),
                self.statuses,
                strict=True,
            ):
                writer.writerow([pos, name, pos, salary, status, "AAA"])


def _remaining_metrics_contest(monkeypatch, tmp_path, statuses):
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: [])
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: [])
    row = ContestRow(
        dk_id=321,
        name="C",
        draft_group=8,
        positions_paid=1,
        start_date="2026-10-04",
        entry_fee=5,
        entries=2,
        contest_state="live",
        prize_pool=100,
    )
    real_collect = collector._collect_source_snapshot
    monkeypatch.setattr(
        collector,
        "_collect_source_snapshot",
        lambda **kwargs: real_collect(dk=_RemainingMetricsDK(statuses), contest_db=_FakeContestDB(by_id=row), **kwargs),
    )
    envelope = build_snapshot_v3_envelope(
        {"NBA": 321},
        generated_at="2026-10-04T12:00:00Z",
        standings_limit=1,
        collector=collect_snapshot,
    )
    return envelope["sports"]["nba"]["contests"][0]


@pytest.mark.parametrize("finished", ["Final", "Postponed", "Cancelled", "Canceled"])
def test_collector_omits_finished_players_from_all_remaining_outputs(monkeypatch, tmp_path, finished):
    contest = _remaining_metrics_contest(
        monkeypatch, tmp_path, [finished, "Delayed", "Suspended", "AAA@BBB 07:00PM ET", finished]
    )

    assert contest["live_metrics"]["avg_salary_per_player_remaining"] == 6571.43
    assert contest["metrics"]["threat"]["field_remaining_pct"] == 87.5
    assert contest["standings"][0]["ownership_remaining_total_pct"] == 80.0
    assert contest["metrics"]["non_cashing"]["top_remaining_players"] == [
        {"player_name": "Bravo", "ownership_remaining_pct": 100.0},
        {"player_name": "Charlie", "ownership_remaining_pct": 100.0},
        {"player_name": "Delta", "ownership_remaining_pct": 100.0},
        {"player_name": "Foxtrot", "ownership_remaining_pct": 100.0},
    ]
    assert [row["player_name"] for row in contest["metrics"]["threat"]["top_swing_players"]] == [
        "Bravo",
        "Charlie",
        "Delta",
        "Foxtrot",
    ]


def test_collector_no_status_pool_omits_remaining_outputs_but_keeps_non_cashing(monkeypatch, tmp_path):
    contest = _remaining_metrics_contest(monkeypatch, tmp_path, ["Masters Tournament"] * 5)

    assert "ownership_remaining_total_pct" not in contest["standings"][0]
    assert "ownership_watchlist" not in contest
    assert "avg_salary_per_player_remaining" not in contest["live_metrics"]
    assert "threat" not in contest["metrics"]
    assert contest["metrics"]["non_cashing"] == {"users_not_cashing": 1, "avg_pmr_remaining": 100.0}


def test_users_not_cashing_is_entries_minus_positions_paid_for_a_fully_parsed_standings_file(monkeypatch, tmp_path):
    lineup = "PG Alpha SG Bravo SF Charlie PF Delta C Echo G Foxtrot F LOCKED UTIL LOCKED"
    header = ["rank", "entry", "name", "pmr", "points", "lineup"]
    dk = _RemainingMetricsDK(["Delayed"] * 5)
    # Paid positions = 4 of 6 entries: ties inside the line, one at it, rows out of score order.
    dk.standings_rows = [
        header,
        ["2", "e1", "tied_a", "0", "90", lineup],
        ["1", "e2", "leader", "0", "100", lineup],
        ["4", "e3", "at_line", "0", "80", lineup],
        ["2", "e4", "tied_b", "0", "90", lineup],
        ["5", "e5", "below_a", "40", "70", lineup],
        ["6", "e6", "below_b", "60", "60", lineup],
    ]
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: [])
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: [])
    row = ContestRow(
        dk_id=321,
        name="C",
        draft_group=8,
        positions_paid=4,
        start_date="2026-10-04",
        entry_fee=5,
        entries=6,
        contest_state="live",
        prize_pool=100,
    )
    real_collect = collector._collect_source_snapshot
    monkeypatch.setattr(
        collector,
        "_collect_source_snapshot",
        lambda **kwargs: real_collect(dk=dk, contest_db=_FakeContestDB(by_id=row), **kwargs),
    )
    envelope = build_snapshot_v3_envelope(
        {"NBA": 321}, generated_at="2026-10-04T12:00:00Z", standings_limit=10, collector=collect_snapshot
    )
    contest = envelope["sports"]["nba"]["contests"][0]

    assert contest["metrics"]["non_cashing"]["users_not_cashing"] == 6 - 4
    assert contest["metrics"]["non_cashing"]["avg_pmr_remaining"] == 50.0


def test_field_remaining_marks_included_locked_lineups_partial_before_truncation(monkeypatch, tmp_path):
    contest = _remaining_metrics_contest(
        monkeypatch, tmp_path, ["Final", "Delayed", "Suspended", "AAA@BBB 07:00PM ET", "Final"]
    )

    assert len(contest["standings"]) == 1
    assert contest["metrics"]["threat"]["field_remaining_pct"] == 87.5
    assert contest["metrics"]["threat"]["field_remaining_is_partial"] is True


class _LeverageMetricsDK(_RemainingMetricsDK):
    def __init__(self):
        super().__init__(["In Progress"] * 5)
        self.standings_rows.extend(
            [
                ["", "", "", "", "", "", "", "George", "F", "12%", "10"],
                ["", "", "", "", "", "", "", "Hotel", "UTIL", "18%", "10"],
            ]
        )

    def download_salary_csv(self, name, draft_group, path):
        super().download_salary_csv(name, draft_group, path)
        with open(path, "a", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(
                [
                    ["F", "George", "F", 3000, "In Progress", "AAA"],
                    ["UTIL", "Hotel", "UTIL", 2000, "In Progress", "AAA"],
                ]
            )


def test_collector_keeps_each_vips_own_completeness_beyond_standings_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: ["hidden-vip", "complete-vip"])
    monkeypatch.setattr(
        collector,
        "fetch_vip_lineups",
        lambda *a, **k: [
            VipLineup("hidden-vip", "2", 100.0, "100", "e2", 35000),
            VipLineup("complete-vip", "3", 90.0, "100", "e3", 44000),
            VipLineup("unmatched-vip", "4", 80.0, "100", "e9", 0),
        ],
    )
    dk = _LeverageMetricsDK()
    complete = "PG Alpha SG Bravo SF Charlie PF Delta C Echo G Foxtrot F George UTIL Hotel"
    hidden = "PG Alpha SG Bravo SF Charlie PF Delta C Echo G LOCKED F LOCKED UTIL LOCKED"
    dk.standings_rows[1:3] = [
        ["1", "e1", "leader", "0", "150", complete],
        ["2", "e2", "hidden-vip", "100", "100", hidden],
        ["3", "e3", "complete-vip", "100", "90", complete],
    ]
    row = ContestRow(
        dk_id=321,
        name="C",
        draft_group=8,
        positions_paid=1,
        start_date="2026-10-04",
        entry_fee=5,
        entries=3,
        contest_state="live",
        prize_pool=100,
    )

    raw = collector._collect_source_snapshot(
        sport="NBA", contest_id=321, standings_limit=1, dk=dk, contest_db=_FakeContestDB(by_id=row)
    )

    assert [row["entry_key"] for row in raw["standings"]] == ["e1"]
    assert raw["ownership"]["field_remaining_pct"] == 180.0
    assert raw["ownership"]["field_remaining_is_partial"] is True
    assert raw["ownership"]["vip_remaining_is_partial_by_entry_key"] == {"e2": True, "e3": False}

    real_collect = collector._collect_source_snapshot
    monkeypatch.setattr(
        collector,
        "_collect_source_snapshot",
        lambda **kwargs: real_collect(dk=dk, contest_db=_FakeContestDB(by_id=row), **kwargs),
    )
    envelope = build_snapshot_v3_envelope(
        {"NBA": 321}, generated_at="2026-10-04T12:00:00Z", standings_limit=1, collector=collect_snapshot
    )
    contest = envelope["sports"]["nba"]["contests"][0]
    assert [row["entry_key"] for row in contest["standings"]] == ["e1"]
    leverage = contest["metrics"]["threat"]["vip_vs_field_leverage"]
    assert [
        (row["entry_key"], row["vip_remaining_pct"], row["uniqueness_delta_pct"], row["is_partial"]) for row in leverage
    ] == [
        ("e2", 150.0, 30.0, True),
        ("e3", 195.0, -15.0, False),
    ]


def test_collector_excludes_unusable_empty_lineup_from_field_and_vip_remaining(monkeypatch, tmp_path):
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: ["empty-vip"])
    monkeypatch.setattr(collector, "fetch_vip_lineups", lambda *a, **k: [])
    dk = _LeverageMetricsDK()
    dk.standings_rows[1:3] = [
        ["1", "e1", "leader", "0", "150", "PG Alpha SG Bravo SF Charlie PF Delta C Echo G Foxtrot F George UTIL Hotel"],
        ["2", "e2", "empty-vip", "100", "100", ""],
    ]
    row = ContestRow(
        dk_id=321, name="C", draft_group=8, positions_paid=1, start_date="2026-10-04", entry_fee=5, entries=2
    )

    raw = collector._collect_source_snapshot(
        sport="NBA", contest_id=321, standings_limit=1, dk=dk, contest_db=_FakeContestDB(by_id=row)
    )

    assert raw["ownership"]["field_remaining_pct"] == 195.0
    assert raw["ownership"]["field_remaining_is_partial"] is True
    assert raw["ownership"]["vip_remaining_by_entry_key"] == {}
    assert raw["ownership"]["vip_remaining_is_partial_by_entry_key"] == {}


def test_collector_keeps_known_ownership_when_included_vip_slot_has_no_ownership(monkeypatch, tmp_path):
    monkeypatch.setattr(collector, "SALARY_DIR", str(tmp_path))
    monkeypatch.setattr(collector, "load_vips", lambda: ["partial-vip"])
    monkeypatch.setattr(
        collector, "fetch_vip_lineups", lambda *a, **k: [VipLineup("partial-vip", "2", 100.0, "100", "e2", 0)]
    )
    sport = collector._sport_choices()["NBA"]
    alpha = Player("Alpha", "PG", "PG", 9000, "In Progress", "AAA", ownership=0.2)
    bravo = Player("Bravo", "SG", "SG", 8000, "In Progress", "AAA", ownership=0.4)
    players = {"Alpha": alpha, "Bravo": bravo}
    complete_lineup = Lineup(sport, players, "SG Bravo")
    partial_lineup = Lineup(sport, players, "PG Alpha SG Bravo")
    # The CSV parser rejects unresolved names and defaults absent ownership to zero.
    # A domain standings adapter can instead supply a slot with unavailable ownership;
    # exercise the collector's defensive contract without replacing its parser.
    partial_slots: list[Any] = [alpha, {"player_name": "Bravo", "game_info": "In Progress"}]
    partial_lineup.lineup = partial_slots
    leader = User(1, "e1", "leader", "100", 150.0, "SG Bravo", lineupobj=complete_lineup)
    vip = User(2, "e2", "partial-vip", "100", 100.0, "PG Alpha SG Bravo", lineupobj=partial_lineup)
    standings = ContestStandings(players, [leader, vip], [vip], 1, 1, 150.0, 1, 100.0, {})
    row = ContestRow(
        dk_id=321,
        name="C",
        draft_group=8,
        positions_paid=1,
        start_date="2026-10-04",
        entry_fee=5,
        entries=2,
        contest_state="live",
        prize_pool=100,
    )
    real_collect = collector._collect_source_snapshot

    def collect_with_standings(**kwargs):
        return real_collect(**kwargs, dk=_FakeDK(), contest_db=_FakeContestDB(by_id=row), standings=standings)

    monkeypatch.setattr(collector, "_collect_source_snapshot", collect_with_standings)
    envelope = build_snapshot_v3_envelope({"NBA": 321}, generated_at="2026-10-04T12:00:00Z", collector=collect_snapshot)
    contest = envelope["sports"]["nba"]["contests"][0]
    assert contest["standings"][1]["ownership_remaining_total_pct"] == 20.0
    threat = contest["metrics"]["threat"]
    assert threat["field_remaining_pct"] == 30.0
    assert threat["field_remaining_is_partial"] is True
    assert threat["vip_vs_field_leverage"] == [
        {
            "vip_entry_key": "e2",
            "entry_key": "e2",
            "display_name": "partial-vip",
            "vip_remaining_pct": 20.0,
            "field_remaining_pct": 30.0,
            "uniqueness_delta_pct": 10.0,
            "is_partial": True,
        }
    ]
