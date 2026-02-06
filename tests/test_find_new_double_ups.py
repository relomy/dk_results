import datetime

from classes.sport import NFLSport
from find_new_double_ups import build_draft_group_start_map, process_sport


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
