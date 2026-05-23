import datetime

import pytest

from dk_results.lobby.parsing import (
    _parse_start_date,
    build_draft_group_start_map,
    get_contests_from_response,
)


class TestGetContestsFromResponse:
    def test_list_response_returned_as_is(self):
        contests = [{"id": 1}, {"id": 2}]
        assert get_contests_from_response(contests) == contests

    def test_dict_with_contests_key(self):
        contests = [{"id": 1}]
        assert get_contests_from_response({"Contests": contests}) == contests

    def test_dict_missing_contests_raises(self):
        with pytest.raises(SystemExit):
            get_contests_from_response({"DraftGroups": []})


class TestParseStartDate:
    def test_parses_iso_with_timezone_suffix(self):
        result = _parse_start_date("2024-09-08T13:00:00.0000000-04:00")
        assert result == datetime.datetime(2024, 9, 8, 13, 0, 0)

    def test_parses_iso_with_utc_suffix(self):
        result = _parse_start_date("2024-01-15T19:30:00.0000000+00:00")
        assert result == datetime.datetime(2024, 1, 15, 19, 30, 0)


class TestBuildDraftGroupStartMap:
    def test_returns_empty_for_empty_inputs(self):
        assert build_draft_group_start_map([], {1}) == {}
        assert build_draft_group_start_map([{"DraftGroupId": 1}], set()) == {}

    def test_maps_allowed_ids_to_datetimes(self):
        groups = [
            {"DraftGroupId": 10, "StartDateEst": "2024-09-08T13:00:00.0000000-04:00"},
            {"DraftGroupId": 20, "StartDateEst": "2024-09-08T18:00:00.0000000-04:00"},
        ]
        result = build_draft_group_start_map(groups, {10})
        assert 10 in result
        assert 20 not in result
        assert result[10] == datetime.datetime(2024, 9, 8, 13, 0, 0)

    def test_skips_missing_draft_group_id(self):
        groups = [{"StartDateEst": "2024-09-08T13:00:00.0000000-04:00"}]
        assert build_draft_group_start_map(groups, {10}) == {}

    def test_skips_missing_start_date(self):
        groups = [{"DraftGroupId": 10}]
        assert build_draft_group_start_map(groups, {10}) == {}

    def test_skips_invalid_start_date(self):
        groups = [{"DraftGroupId": 10, "StartDateEst": "not-a-date"}]
        assert build_draft_group_start_map(groups, {10}) == {}
