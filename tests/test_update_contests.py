import datetime

import update_contests


def test_parse_start_date_handles_str_and_datetime():
    dt = datetime.datetime(2026, 1, 1, 0, 0, 0)
    assert update_contests._parse_start_date(dt) == dt
    assert update_contests._parse_start_date("2026-01-01 00:00:00") == dt
    assert update_contests._parse_start_date("bad-date") is None


def test_format_contest_announcement_adds_relative_time():
    now = datetime.datetime.now().replace(microsecond=0)
    start_date = now + datetime.timedelta(minutes=13, seconds=30)

    msg = update_contests._format_contest_announcement(
        "Contest starting soon",
        "NBA",
        "Test Contest",
        start_date.isoformat(sep=" "),
        123,
    )

    assert "(⏳ 13m)" in msg
    assert "Contest starting soon" in msg
