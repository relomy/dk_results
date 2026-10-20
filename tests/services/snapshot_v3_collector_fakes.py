"""Shared fakes and builders for the snapshot_v3 collector tests.

Edge stubs for DraftKings and the contest database, plus the Player and
standings-user builders more than one collector test module uses.
"""

from types import SimpleNamespace

from dk_results.domain.player import Player


class _FakeDK:
    """DraftKings edge stub: no network, records the salary path it was handed."""

    def __init__(self, *, detail=None, leaderboard=None, standings_rows=None, draftables=None, draftables_error=None):
        self._detail = detail or {}
        self._leaderboard = leaderboard if leaderboard is not None else {}
        self.standings_rows = standings_rows if standings_rows is not None else [["header"], ["row"]]
        self.salary_path = None
        self._draftables = draftables if draftables is not None else {"draftables": [], "competitions": []}
        self._draftables_error = draftables_error
        self.draftables_requests: list[int] = []

    def get_contest_detail(self, _contest_id):
        return self._detail

    def get_leaderboard(self, _contest_id):
        return self._leaderboard

    def download_salary_csv(self, _name, _draft_group, path):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            handle.write("Position,Name+ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame\n")
        self.salary_path = path

    def download_contest_rows(self, _dk_id, timeout=30, cookies_dump_file=None, contest_dir=None):
        return self.standings_rows

    def get_draftables(self, draft_group, timeout=None):
        self.draftables_requests.append(draft_group)
        if self._draftables_error is not None:
            raise self._draftables_error
        return self._draftables


class _FakeContestDB:
    """In-memory ContestDatabase edge stub."""

    def __init__(self, *, by_id=None, candidates=None, live=None, state=None, contract=None, completed_at=None):
        self._by_id = by_id
        self._completed_at = completed_at
        self._candidates = candidates or []
        self._live = live
        self._state = state
        self._contract = contract
        self.closed = False

    def get_live_contest_candidates(self, _name, entry_fee=None, keyword=None, limit=None):
        return self._candidates

    def get_contest_by_id(self, _contest_id):
        return self._by_id

    def get_live_contest(self, _name, _min_fee, _keyword):
        return self._live

    def get_contest_state(self, _dk_id):
        return self._state

    def get_contest_contract_metadata(self, _dk_id):
        return self._contract

    def get_contest_completed_at(self, _dk_id):
        return self._completed_at

    def close(self):
        self.closed = True


def _salary_player(name, team, game_info, draftable_id):
    """A Player as the salary CSV + standings parse would leave it (sheet matchup_info included)."""
    player = Player(name, "QB", "QB/FLEX", 8000, game_info, team, draftable_id=draftable_id)
    player.update_stats("QB", "12.5%", "20.0")
    return player


def _by_name(rows: list[dict]) -> dict[str, dict]:
    return {row["name"]: row for row in rows}


def _field_user(rank, entry_key, ownership, *, game_info="Live", salary=None):
    lineupobj = (
        None
        if ownership is None
        else SimpleNamespace(lineup=[SimpleNamespace(game_info=game_info, ownership=ownership, salary=salary)])
    )
    return SimpleNamespace(
        rank=str(rank), pts="10", pmr="0", player_id=entry_key, name=f"u{entry_key}", salary=0, lineupobj=lineupobj
    )
