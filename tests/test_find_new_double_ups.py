import argparse
import datetime
import runpy
import sys
import types

import pytest
from requests.cookies import RequestsCookieJar

from classes.contest import Contest
from classes.sport import NFLShowdownSport, NFLSport, Sport
from find_new_double_ups import (
    build_draft_group_start_map,
    contest_meets_criteria,
    format_discord_messages,
    get_contests_from_response,
    get_dk_lobby,
    get_double_ups,
    get_draft_groups_from_response,
    get_salary_date,
    get_stats,
    is_time_between,
    log_draft_group_event,
    parse_args,
    process_sport,
    send_discord_notification,
    set_quiet_verbosity,
    valid_date,
)


def test_build_draft_group_start_map_filters_and_parses():
    draft_groups = [
        {"DraftGroupId": 10, "StartDateEst": "2024-02-01T12:30:00.000-05:00"},
        {"DraftGroupId": 20, "StartDateEst": "2024-02-02T13:00:00.000-05:00"},
        {"DraftGroupId": 30, "StartDateEst": None},
        {"DraftGroupId": 40, "StartDateEst": "invalid"},
    ]
    allowed_ids = {10, 30, 40}

    result = build_draft_group_start_map(draft_groups, allowed_ids)

    assert result == {10: datetime.datetime(2024, 2, 1, 12, 30, 0)}


def test_process_sport_syncs_draft_group_start_dates(monkeypatch):
    contest = {
        "sd": "1706781000000",
        "n": "Test Contest",
        "id": 101,
        "dg": 111,
        "po": 1000,
        "m": 200,
        "a": 10,
        "ec": 0,
        "mec": 1,
        "attr": {"IsDoubleUp": True, "IsGuaranteed": True},
        "gameType": "Classic",
        "gameTypeId": 1,
    }
    draft_groups = [
        {
            "DraftGroupId": 111,
            "StartDateEst": "2024-02-01T12:30:00.000-05:00",
        },
        {
            "DraftGroupId": 222,
            "StartDateEst": "2024-02-02T13:00:00.000-05:00",
        },
        {
            "DraftGroupId": 333,
            "StartDateEst": "2024-02-03T14:00:00.000-05:00",
        },
    ]

    def fake_get_dk_lobby(_sport, _url):
        response = {"DraftGroups": draft_groups}
        return [contest], [111, 222], response

    class FakeDB:
        def __init__(self):
            self.start_map = None

        def create_table(self):
            return None

        def sync_draft_group_start_dates(self, start_map):
            self.start_map = start_map
            return 1

        def compare_contests(self, contests):
            return [c.id for c in contests]

        def insert_contests(self, _contests):
            return None

    monkeypatch.setattr("find_new_double_ups.get_dk_lobby", fake_get_dk_lobby)
    db = FakeDB()

    process_sport("NFL", {"NFL": NFLSport}, db, None)

    assert db.start_map == {
        111: datetime.datetime(2024, 2, 1, 12, 30),
        222: datetime.datetime(2024, 2, 2, 13, 0),
    }


def _contest_payload(dk_id: int):
    return {
        "sd": "1700000000000",
        "n": "Contest",
        "id": dk_id,
        "dg": 10,
        "po": 0,
        "m": 200,
        "a": 10,
        "ec": 0,
        "mec": 1,
        "attr": {"IsDoubleUp": True, "IsGuaranteed": True},
        "gameType": "Classic",
        "gameTypeId": 1,
    }


def test_send_discord_notification_no_bot():
    send_discord_notification(None, "NBA", "msg")


def test_send_discord_notification_formats_message():
    class FakeBot:
        def __init__(self):
            self.sent = []

        def send_message(self, message: str):
            self.sent.append(message)

    bot = FakeBot()
    send_discord_notification(bot, "NBA", "New contest")
    assert bot.sent == [":basketball: New contest <@&1034206287153594470>"]


def test_get_contests_from_response_list_and_dict():
    assert get_contests_from_response([{1: 2}]) == [{1: 2}]
    assert get_contests_from_response({"Contests": [1]}) == [1]


def test_get_contests_from_response_invalid(monkeypatch):
    monkeypatch.setattr(
        "find_new_double_ups.sys.exit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit()),
    )
    with pytest.raises(SystemExit):
        get_contests_from_response({"Other": []})


def test_log_draft_group_event_includes_reason(monkeypatch):
    captured = []

    def fake_log(level, msg, *args):
        captured.append(msg % args)

    monkeypatch.setattr("find_new_double_ups.logger.log", fake_log)

    class DummySport(Sport):
        name = "TEST"

    log_draft_group_event(
        "Skip",
        DummySport,
        datetime.datetime(2024, 1, 1, 0, 0, 0),
        10,
        "Featured",
        "(Main)",
        1,
        2,
        reason="suffix mismatch",
    )

    assert any("reason" in msg for msg in captured)


def test_get_draft_groups_from_response_filters():
    class DummySport(Sport):
        name = "TEST"
        suffixes = [r"\(Main\)"]
        allow_suffixless_draft_groups = False
        contest_restraint_time = datetime.time(18, 0)
        contest_restraint_game_type_id = 99

    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Other",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 1,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 2,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Alt)",
                "DraftGroupId": 3,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 4,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 1,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 5,
                "StartDateEst": "2024-02-01T16:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(Main)",
                "DraftGroupId": 6,
                "StartDateEst": "2024-02-01T20:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 99,
            },
        ]
    }

    result = get_draft_groups_from_response(response, DummySport)
    assert result == [6]


def test_get_draft_groups_from_response_nfl_showdown():
    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(ABC @ DEF)",
                "DraftGroupId": 10,
                "StartDateEst": "2024-02-01T20:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(ABC @ DEF)",
                "DraftGroupId": 11,
                "StartDateEst": "2024-02-01T20:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": "(XYZ @ QRS)",
                "DraftGroupId": 12,
                "StartDateEst": "2024-02-01T21:00:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 96,
            },
        ]
    }

    result = get_draft_groups_from_response(response, NFLShowdownSport)
    assert result == [12]


def test_build_draft_group_start_map_empty():
    assert build_draft_group_start_map([], set()) == {}


def test_valid_date_rejects_invalid():
    with pytest.raises(argparse.ArgumentTypeError):
        valid_date("bad")


def test_get_stats_counts_dubs():
    contests = [Contest(_contest_payload(1), "NBA")]
    stats = get_stats(contests)
    assert stats[contests[0].start_dt.strftime("%Y-%m-%d")]["dubs"][10] == 1


def test_get_double_ups_filters():
    contests = [Contest(_contest_payload(1), "NBA")]
    result = get_double_ups(contests, [10])
    assert [c.id for c in result] == [1]


def test_contest_meets_criteria_false():
    contest = Contest(_contest_payload(1), "NBA")
    assert (
        contest_meets_criteria(
            contest,
            {
                "entries": 300,
                "draft_groups": [],
                "min_entry_fee": 5,
                "max_entry_fee": 50,
            },
        )
        is False
    )


def test_get_salary_date():
    date_val = get_salary_date({"StartDateEst": "2024-02-01T12:30:00.000-05:00"})
    assert date_val == datetime.date(2024, 2, 1)


def test_is_time_between_crosses_midnight():
    begin = datetime.time(23, 0)
    end = datetime.time(1, 0)
    assert is_time_between(begin, end, datetime.time(0, 30)) is True


def test_set_quiet_verbosity():
    set_quiet_verbosity()


def test_format_discord_messages():
    contests = [Contest(_contest_payload(1), "NBA")]
    msg = format_discord_messages(contests)
    assert "New dub found!" in msg


def test_process_sport_invalid_name(monkeypatch):
    with pytest.raises(Exception):
        process_sport("BAD", {}, None, None)


def test_process_sport_sends_notification(monkeypatch):
    contest = _contest_payload(1)
    draft_groups = [10]

    def fake_get_dk_lobby(_sport, _url):
        response = {
            "DraftGroups": [
                {
                    "DraftGroupId": 10,
                    "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                }
            ]
        }
        return [contest], draft_groups, response

    class FakeDB:
        def __init__(self):
            self.inserted = []

        def create_table(self):
            return None

        def sync_draft_group_start_dates(self, _start_map):
            return 0

        def compare_contests(self, _contests):
            return [1]

        def insert_contests(self, contests):
            self.inserted.extend(contests)

    class FakeBot:
        def __init__(self):
            self.sent = []

        def send_message(self, message: str):
            self.sent.append(message)

    monkeypatch.setattr("find_new_double_ups.get_dk_lobby", fake_get_dk_lobby)

    class DummySport(Sport):
        name = "NBA"
        dub_min_entry_fee = 5
        dub_min_entries = 125

    db = FakeDB()
    bot = FakeBot()
    monkeypatch.setenv("DFS_STATE_DIR", "/tmp")
    recorded = []
    monkeypatch.setattr(
        "contests_state.upsert_contests", lambda contests: recorded.extend(contests)
    )

    process_sport("NBA", {"NBA": DummySport}, db, bot)

    assert recorded
    assert bot.sent


def test_get_dk_lobby_uses_requests(monkeypatch):
    class DummySport(Sport):
        name = "NBA"

    class FakeResp:
        def json(self):
            return {"Contests": [], "DraftGroups": []}

    monkeypatch.setattr("find_new_double_ups.requests.get", lambda *_a, **_k: FakeResp())

    contests, draft_groups, resp = get_dk_lobby(DummySport, "http://example")
    assert contests == []
    assert draft_groups == []
    assert resp == {"Contests": [], "DraftGroups": []}


def test_get_draft_groups_allows_suffixless():
    class DummySport(Sport):
        name = "TEST"
        allow_suffixless_draft_groups = True

    response = {
        "DraftGroups": [
            {
                "DraftGroupTag": "Featured",
                "ContestStartTimeSuffix": None,
                "DraftGroupId": 1,
                "StartDateEst": "2024-02-01T12:30:00.000-05:00",
                "ContestTypeId": 1,
                "GameTypeId": 1,
            }
        ]
    }
    assert get_draft_groups_from_response(response, DummySport) == [1]


def test_get_stats_counts_duplicate_dubs():
    contests = [Contest(_contest_payload(1), "NBA"), Contest(_contest_payload(2), "NBA")]
    stats = get_stats(contests)
    date_key = contests[0].start_dt.strftime("%Y-%m-%d")
    assert stats[date_key]["dubs"][10] == 2


def test_is_time_between_standard_range():
    assert is_time_between(datetime.time(9, 0), datetime.time(17, 0), datetime.time(12, 0))
    assert not is_time_between(
        datetime.time(9, 0), datetime.time(17, 0), datetime.time(8, 0)
    )


def test_parse_args_parses_sport_and_quiet(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-q"])
    args = parse_args({"NFL": NFLSport})
    assert args.sport == ["NFL"]
    assert args.quiet is True


def test_main_executes_with_fakes(monkeypatch, tmp_path):
    fake_cookieservice = types.ModuleType("classes.cookieservice")
    fake_cookieservice.get_dk_cookies = lambda *_a, **_k: ({}, RequestsCookieJar())

    class FakeDB:
        def __init__(self, *_a, **_k):
            pass

        def create_table(self):
            return None

        def sync_draft_group_start_dates(self, *_a, **_k):
            return 0

        def compare_contests(self, *_a, **_k):
            return []

        def insert_contests(self, *_a, **_k):
            return None

        def close(self):
            return None

    fake_contestdatabase = types.ModuleType("classes.contestdatabase")
    fake_contestdatabase.ContestDatabase = FakeDB

    class FakeResp:
        def json(self):
            return {"Contests": [], "DraftGroups": []}

    monkeypatch.setitem(sys.modules, "classes.cookieservice", fake_cookieservice)
    monkeypatch.setitem(sys.modules, "classes.contestdatabase", fake_contestdatabase)
    monkeypatch.setattr("requests.get", lambda *_a, **_k: FakeResp())
    monkeypatch.setenv("DISCORD_WEBHOOK", "")
    monkeypatch.setenv("DFS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("contests_state.upsert_contests", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL"])

    runpy.run_module("find_new_double_ups", run_name="__main__")


def test_get_stats_counts_multiple_entry_fees():
    contest1 = _contest_payload(1)
    contest2 = _contest_payload(2)
    contest2["a"] = 25
    contests = [Contest(contest1, "NBA"), Contest(contest2, "NBA")]

    stats = get_stats(contests)
    date_key = contests[0].start_dt.strftime("%Y-%m-%d")

    assert stats[date_key]["dubs"][10] == 1
    assert stats[date_key]["dubs"][25] == 1


def test_main_with_webhook_and_quiet(monkeypatch):
    fake_cookieservice = types.ModuleType("classes.cookieservice")
    fake_cookieservice.get_dk_cookies = lambda *_a, **_k: ({}, RequestsCookieJar())

    class FakeDB:
        def __init__(self, *_a, **_k):
            pass

        def create_table(self):
            return None

        def sync_draft_group_start_dates(self, *_a, **_k):
            return 0

        def compare_contests(self, *_a, **_k):
            return []

        def insert_contests(self, *_a, **_k):
            return None

        def close(self):
            return None

    fake_contestdatabase = types.ModuleType("classes.contestdatabase")
    fake_contestdatabase.ContestDatabase = FakeDB

    class FakeResp:
        def json(self):
            return {"Contests": [], "DraftGroups": []}

    monkeypatch.setitem(sys.modules, "classes.cookieservice", fake_cookieservice)
    monkeypatch.setitem(sys.modules, "classes.contestdatabase", fake_contestdatabase)
    monkeypatch.setattr("requests.get", lambda *_a, **_k: FakeResp())
    monkeypatch.setenv("DISCORD_WEBHOOK", "https://example.test/hook")
    monkeypatch.setenv("DFS_STATE_DIR", "/tmp")
    monkeypatch.setattr("contests_state.upsert_contests", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-q"])

    runpy.run_module("find_new_double_ups", run_name="__main__")
