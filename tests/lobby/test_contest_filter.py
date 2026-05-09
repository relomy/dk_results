import datetime

from classes.contest import Contest

from dk_results.lobby.contest_filter import filter_double_ups, largest_by_entries


def _payload(
    dk_id: int,
    *,
    entries: int = 200,
    fee: int = 25,
    draft_group: int = 10,
    is_double_up: bool = True,
    is_guaranteed: bool = True,
    max_entry_count: int = 1,
    game_type_id: int = 1,
    name: str | None = None,
    timestamp: str = "1700000000000",
):
    return {
        "sd": timestamp,
        "n": name if name is not None else f"Contest {dk_id}",
        "id": dk_id,
        "dg": draft_group,
        "po": 0,
        "m": entries,
        "a": fee,
        "ec": 0,
        "mec": max_entry_count,
        "attr": {"IsDoubleUp": is_double_up, "IsGuaranteed": is_guaranteed},
        "gameType": "Classic",
        "gameTypeId": game_type_id,
    }


def _contest(dk_id: int, sport: str = "NFL", **kwargs) -> Contest:
    return Contest(_payload(dk_id, **kwargs), sport)


# ── base double-up predicate ──────────────────────────────────────────────────

def test_passes_basic_double_up():
    c = _contest(1)
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25)
    assert [x.id for x in result] == [1]


def test_rejects_non_double_up():
    c = _contest(1, is_double_up=False)
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25) == []


def test_rejects_non_guaranteed():
    c = _contest(1, is_guaranteed=False)
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25) == []


def test_rejects_multi_entry():
    c = _contest(1, max_entry_count=3)
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25) == []


# ── fee range ─────────────────────────────────────────────────────────────────

def test_exact_fee_match():
    contests = [_contest(1, fee=25), _contest(2, fee=10), _contest(3, fee=50)]
    result = filter_double_ups(contests, min_entry_fee=25, max_entry_fee=25)
    assert [x.id for x in result] == [1]


def test_fee_range_inclusive_bounds():
    contests = [_contest(1, fee=5), _contest(2, fee=25), _contest(3, fee=50), _contest(4, fee=51)]
    result = filter_double_ups(contests, min_entry_fee=5, max_entry_fee=50)
    assert [x.id for x in result] == [1, 2, 3]


def test_fee_below_min_rejected():
    c = _contest(1, fee=4)
    assert filter_double_ups([c], min_entry_fee=5, max_entry_fee=50) == []


def test_fee_above_max_rejected():
    c = _contest(1, fee=51)
    assert filter_double_ups([c], min_entry_fee=5, max_entry_fee=50) == []


# ── start_date ────────────────────────────────────────────────────────────────

def test_start_date_match():
    # timestamp 1700000000000 ms → 2023-11-14 in UTC
    c = _contest(1, timestamp="1700000000000")
    dt = c.start_dt.date()
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, start_date=dt)
    assert [x.id for x in result] == [1]


def test_start_date_mismatch_rejected():
    c = _contest(1, timestamp="1700000000000")
    wrong_date = datetime.date(2000, 1, 1)
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, start_date=wrong_date) == []


def test_no_start_date_constraint_passes_all_dates():
    c1 = _contest(1, timestamp="1700000000000")
    c2 = _contest(2, timestamp="1710000000000")
    result = filter_double_ups([c1, c2], min_entry_fee=25, max_entry_fee=25)
    assert len(result) == 2


# ── draft_groups ──────────────────────────────────────────────────────────────

def test_draft_group_in_set_passes():
    c = _contest(1, draft_group=10)
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, draft_groups=[10, 20])
    assert [x.id for x in result] == [1]


def test_draft_group_not_in_set_rejected():
    c = _contest(1, draft_group=99)
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, draft_groups=[10, 20]) == []


def test_no_draft_group_constraint_passes_all():
    contests = [_contest(1, draft_group=10), _contest(2, draft_group=99)]
    result = filter_double_ups(contests, min_entry_fee=25, max_entry_fee=25)
    assert len(result) == 2


# ── min_entries ───────────────────────────────────────────────────────────────

def test_min_entries_passes_at_threshold():
    c = _contest(1, entries=125)
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, min_entries=125)
    assert [x.id for x in result] == [1]


def test_min_entries_rejects_below_threshold():
    c = _contest(1, entries=124)
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, min_entries=125) == []


def test_min_entries_zero_default_passes_all():
    c = _contest(1, entries=0)
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25)
    assert [x.id for x in result] == [1]


# ── game_type_id ──────────────────────────────────────────────────────────────

def test_game_type_id_match():
    c = _contest(1, game_type_id=87)
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, game_type_id=87)
    assert [x.id for x in result] == [1]


def test_game_type_id_mismatch_rejected():
    c = _contest(1, game_type_id=6)
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, game_type_id=87) == []


def test_no_game_type_id_constraint_passes_all():
    contests = [_contest(1, game_type_id=6), _contest(2, game_type_id=87)]
    result = filter_double_ups(contests, min_entry_fee=25, max_entry_fee=25)
    assert len(result) == 2


# ── name_contains / name_excludes ─────────────────────────────────────────────

def test_name_contains_match():
    c = _contest(1, name="Main Slate Double Up")
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, name_contains="Main")
    assert [x.id for x in result] == [1]


def test_name_contains_mismatch_rejected():
    c = _contest(1, name="Satellite Double Up")
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, name_contains="Main") == []


def test_name_excludes_match_rejected():
    c = _contest(1, name="Main Excluded Double Up")
    assert filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, name_excludes="Excluded") == []


def test_name_excludes_no_match_passes():
    c = _contest(1, name="Main Slate Double Up")
    result = filter_double_ups([c], min_entry_fee=25, max_entry_fee=25, name_excludes="Excluded")
    assert [x.id for x in result] == [1]


def test_name_contains_and_excludes_combined():
    contests = [
        _contest(1, name="Main Slate"),
        _contest(2, name="Main Excluded"),
        _contest(3, name="Other Slate"),
    ]
    result = filter_double_ups(
        contests, min_entry_fee=25, max_entry_fee=25, name_contains="Main", name_excludes="Excluded"
    )
    assert [x.id for x in result] == [1]


# ── empty input ───────────────────────────────────────────────────────────────

def test_empty_contests_returns_empty():
    assert filter_double_ups([], min_entry_fee=25, max_entry_fee=25) == []


# ── largest_by_entries ────────────────────────────────────────────────────────

def test_largest_by_entries_returns_max():
    contests = [_contest(1, entries=150), _contest(2, entries=300), _contest(3, entries=200)]
    assert largest_by_entries(contests).id == 2


def test_largest_by_entries_single_item():
    c = _contest(1, entries=100)
    assert largest_by_entries([c]).id == 1


def test_largest_by_entries_empty_returns_none():
    assert largest_by_entries([]) is None


# ── caller 1 pattern: dkcontests (exact fee, date, optional filters) ──────────

def test_dkcontests_caller_pattern():
    date = datetime.date(2023, 11, 14)
    timestamp = "1700000000000"
    contests = [
        _contest(1, fee=25, entries=150, name="Main Slate", timestamp=timestamp),
        _contest(2, fee=25, entries=260, name="Main Slate", timestamp=timestamp),
        _contest(3, fee=25, entries=280, name="Main Excluded", timestamp=timestamp),
        _contest(4, fee=10, entries=400, name="Main Slate", timestamp=timestamp),
    ]
    result = largest_by_entries(
        filter_double_ups(
            contests,
            min_entry_fee=25,
            max_entry_fee=25,
            start_date=date,
            name_contains="Main",
            name_excludes="Excluded",
        )
    )
    assert result is not None
    assert result.id == 2


# ── caller 2 pattern: double_ups (fee range, draft groups, min entries) ───────

def test_double_ups_caller_pattern():
    contests = [
        _contest(1, fee=5, draft_group=10, entries=130),
        _contest(2, fee=25, draft_group=10, entries=200),
        _contest(3, fee=51, draft_group=10, entries=500),  # above max fee
        _contest(4, fee=10, draft_group=99, entries=200),  # wrong draft group
        _contest(5, fee=10, draft_group=10, entries=100),  # below min entries
    ]
    result = filter_double_ups(
        contests,
        min_entry_fee=5,
        max_entry_fee=50,
        draft_groups=[10, 20],
        min_entries=125,
    )
    assert [x.id for x in result] == [1, 2]
