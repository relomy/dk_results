import datetime
import sys

import pytest
from dfs_common.discord import WebhookSender
from requests.cookies import RequestsCookieJar

import dk_results.cli.find_new_double_ups as find_mod
from dk_results.cli.find_new_double_ups import (
    _init_runtime,
    parse_args,
    process_sport,
    send_discord_notification,
    set_quiet_verbosity,
)
from dk_results.domain.contest import Contest
from dk_results.domain.sport import NFLSport, Sport
from dk_results.lobby.formatting import format_discord_messages


def test_find_new_double_ups_exposes_webhook_sender():
    assert find_mod.WebhookSender is WebhookSender


def test_init_runtime_keeps_existing_loggers(monkeypatch):
    calls = {"configure_logging": 0}

    monkeypatch.setattr(
        "dk_results.cli.find_new_double_ups.configure_logging",
        lambda: calls.__setitem__("configure_logging", calls["configure_logging"] + 1),
    )

    _init_runtime()

    assert calls["configure_logging"] == 1


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

    def fake_get_dk_lobby(_sport, _url, **_kwargs):
        response = {"DraftGroups": draft_groups}
        return [contest], [111, 222], response

    class FakeDB:
        def __init__(self):
            self.start_map = None

        def ensure_schema(self):
            return None

        def sync_draft_group_start_dates(self, start_map):
            self.start_map = start_map
            return 1

        def compare_contests(self, contests):
            return [c.id for c in contests]

        def insert_contests(self, _contests):
            return None

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.get_dk_lobby", fake_get_dk_lobby)
    monkeypatch.setattr("dk_results.cli.find_new_double_ups._upsert_contests", lambda *_a, **_k: None)
    db = FakeDB()

    process_sport("NFL", {"NFL": NFLSport}, db, None)

    assert db.start_map == {
        111: datetime.datetime(2024, 2, 1, 12, 30),
        222: datetime.datetime(2024, 2, 2, 13, 0),
    }


def test_upsert_contests_uses_dfs_common(monkeypatch):
    contest = Contest.from_lobby(_contest_payload(303), "NBA")
    calls = {"db_path": None, "rows": None}

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.state.contests_db_path", lambda: "/tmp/contests.db")

    def fake_upsert(db_path, rows):
        calls["db_path"] = db_path
        calls["rows"] = list(rows)

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.contests.upsert_contests", fake_upsert)

    find_mod._upsert_contests([contest])

    assert calls["db_path"] == "/tmp/contests.db"
    assert calls["rows"] and calls["rows"][0]["dk_id"] == 303


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
    contest = Contest.from_lobby(_contest_payload(1), "NBA")
    send_discord_notification(None, "NBA", [contest])


def test_send_discord_notification_formats_message():
    class FakeBot:
        def __init__(self):
            self.sent = []

        def send_message(self, message: str):
            self.sent.append(message)

    bot = FakeBot()
    contest = Contest.from_lobby(_contest_payload(1), "NBA")
    send_discord_notification(bot, "NBA", [contest])
    assert len(bot.sent) == 1
    assert bot.sent[0].startswith(":basketball: New double-up found: 🏀 NBA — Contest\n")
    assert bot.sent[0].endswith("<@&1034206287153594470>")


def test_send_discord_notification_gates_unmapped_sport():
    """A sport absent from the role map gets no double-up announcement at all."""

    class FakeBot:
        def __init__(self):
            self.sent = []

        def send_message(self, message: str):
            self.sent.append(message)

    bot = FakeBot()
    contest = Contest.from_lobby(_contest_payload(1), "MLB")
    send_discord_notification(bot, "MLB", [contest])
    assert bot.sent == []


def test_set_quiet_verbosity():
    set_quiet_verbosity()


def test_format_discord_messages():
    contests = [Contest.from_lobby(_contest_payload(1), "NBA")]
    msg = format_discord_messages(contests)
    assert "New dub found!" in msg


def test_process_sport_invalid_name(monkeypatch):
    with pytest.raises(Exception):
        process_sport("BAD", {}, None, None)


def test_process_sport_sends_notification(monkeypatch):
    contest = _contest_payload(1)
    draft_groups = [10]

    def fake_get_dk_lobby(_sport, _url, **_kwargs):
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

        def ensure_schema(self):
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

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.get_dk_lobby", fake_get_dk_lobby)

    class DummySport(Sport):
        name = "NBA"
        dub_min_entry_fee = 5
        dub_min_entries = 125

    db = FakeDB()
    bot = FakeBot()
    monkeypatch.setenv("DFS_STATE_DIR", "/tmp")
    recorded = []
    monkeypatch.setattr(
        "dk_results.cli.find_new_double_ups._upsert_contests", lambda contests: recorded.extend(contests)
    )

    process_sport("NBA", {"NBA": DummySport}, db, bot)

    assert recorded
    assert bot.sent


def test_parse_args_parses_sport_and_quiet(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-q"])
    args = parse_args({"NFL": NFLSport})
    assert args.sport == ["NFL"]
    assert args.quiet is True


def test_main_executes_with_fakes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "dk_results.draftkings.cookies.get_dk_cookies",
        lambda *_a, **_k: ({}, RequestsCookieJar()),
    )

    class FakeDB:
        def __init__(self, *_a, **_k):
            pass

        def ensure_schema(self):
            return None

        def sync_draft_group_start_dates(self, *_a, **_k):
            return 0

        def compare_contests(self, *_a, **_k):
            return []

        def insert_contests(self, *_a, **_k):
            return None

        def close(self):
            return None

    class FakeResp:
        def json(self):
            return {"Contests": [], "DraftGroups": []}

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.ContestDatabase", FakeDB)
    monkeypatch.setattr("requests.get", lambda *_a, **_k: FakeResp())
    monkeypatch.setenv("DISCORD_WEBHOOK", "")
    monkeypatch.setenv("DFS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("dk_results.cli.find_new_double_ups._upsert_contests", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL"])

    find_mod.main()


def test_main_with_webhook_and_quiet(monkeypatch):
    monkeypatch.setattr(
        "dk_results.draftkings.cookies.get_dk_cookies",
        lambda *_a, **_k: ({}, RequestsCookieJar()),
    )

    class FakeDB:
        def __init__(self, *_a, **_k):
            pass

        def ensure_schema(self):
            return None

        def sync_draft_group_start_dates(self, *_a, **_k):
            return 0

        def compare_contests(self, *_a, **_k):
            return []

        def insert_contests(self, *_a, **_k):
            return None

        def close(self):
            return None

    class FakeResp:
        def json(self):
            return {"Contests": [], "DraftGroups": []}

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.ContestDatabase", FakeDB)
    monkeypatch.setattr("requests.get", lambda *_a, **_k: FakeResp())
    monkeypatch.setenv("DISCORD_WEBHOOK", "https://example.test/hook")
    monkeypatch.setenv("DFS_STATE_DIR", "/tmp")
    monkeypatch.setattr("dk_results.cli.find_new_double_ups._upsert_contests", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL", "-q"])

    find_mod.main()


def test_main_resolves_db_path_once(monkeypatch):
    monkeypatch.setattr(
        "dk_results.draftkings.cookies.get_dk_cookies",
        lambda *_a, **_k: ({}, RequestsCookieJar()),
    )

    class FakeDB:
        def __init__(self, *_a, **_k):
            pass

        def ensure_schema(self):
            return None

        def sync_draft_group_start_dates(self, *_a, **_k):
            return 0

        def compare_contests(self, *_a, **_k):
            return []

        def close(self):
            return None

    class FakeResp:
        def json(self):
            return {"Contests": [], "DraftGroups": []}

    calls = {"contests_db_path": 0, "init_schema": 0}

    def fake_contests_db_path():
        calls["contests_db_path"] += 1
        return "/tmp/contests.db"

    def fake_init_schema(_path):
        calls["init_schema"] += 1
        return "/tmp/contests.db"

    monkeypatch.setattr("dk_results.cli.find_new_double_ups.ContestDatabase", FakeDB)
    monkeypatch.setattr("requests.get", lambda *_a, **_k: FakeResp())
    monkeypatch.setattr("dk_results.cli.find_new_double_ups.state.contests_db_path", fake_contests_db_path)
    monkeypatch.setattr("dk_results.cli.find_new_double_ups.contests.init_schema", fake_init_schema)
    monkeypatch.setenv("DISCORD_WEBHOOK", "")
    monkeypatch.setattr(sys, "argv", ["prog", "-s", "NFL"])

    find_mod.main()

    assert calls == {"contests_db_path": 1, "init_schema": 1}
