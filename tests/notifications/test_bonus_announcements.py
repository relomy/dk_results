import sqlite3
from dataclasses import dataclass

import dk_results.notifications.bonus_announcements as bonus_announcements
from dk_results.notifications.bonus_announcements import announce_vip_bonuses


class _Sender:
    def __init__(self):
        self.messages: list[str] = []
        self.raise_error = False

    def send_message(self, message: str) -> None:
        if self.raise_error:
            raise RuntimeError("send failed")
        self.messages.append(message)


def _build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    bonus_announcements._SqliteBonusStateStore(conn).create_table()
    return conn


@dataclass
class _StateStore:
    old_count: int = 0
    updated: bool = True
    ensured: bool = False
    committed: bool = False
    compare_and_set_args: tuple[int, int] | None = None

    def load_count(self, _key):
        return self.old_count

    def ensure_row(self, _key) -> None:
        self.ensured = True

    def compare_and_set(self, _key, old_count: int, new_count: int) -> bool:
        self.compare_and_set_args = (old_count, new_count)
        return self.updated

    def commit(self) -> None:
        self.committed = True


def test_announce_vip_bonuses_skips_empty_lineups():
    conn = _build_conn()
    sender = _Sender()
    sent = announce_vip_bonuses(
        conn=conn,
        sport="GOLF",
        contest_id=123,
        vip_lineups=[],
        sender=sender,
    )
    assert sent == 0
    assert sender.messages == []


def test_announce_candidate_uses_internal_state_store_seam():
    candidate = bonus_announcements.BonusCandidate(
        display_name="Rory McIlroy",
        normalized_player_name="Rory McIlroy",
        bonus_code="EAG",
        new_count=3,
        max_ownership=0.347,
        vip_users=["amy"],
    )
    sender = _Sender()
    state_store = _StateStore(old_count=1)

    result = bonus_announcements._announce_candidate(
        state_store=state_store,
        sender=sender,
        sport="GOLF",
        contest_id=777,
        candidate=candidate,
    )

    assert result.persisted_announcements == 2
    assert result.webhook_messages == 2
    assert state_store.ensured is True
    assert state_store.committed is True
    assert state_store.compare_and_set_args == (1, 3)
    assert len(sender.messages) == 2


def test_announce_vip_bonuses_first_run_insert_and_update():
    conn = _build_conn()
    sender = _Sender()
    vip_lineups = [
        {
            "user": "zeta",
            "players": [
                {"name": "Rory McIlroy", "stats": "22 PAR, 1 EAG", "ownership": 0.347},
            ],
        }
    ]

    sent = announce_vip_bonuses(
        conn=conn,
        sport="GOLF",
        contest_id=777,
        vip_lineups=vip_lineups,
        sender=sender,
    )

    assert sent == 1
    assert sender.messages[0] == "GOLF: Rory McIlroy (34.7%) recorded an eagle (+8 pts) (VIPs: zeta)"
    row = conn.execute(
        """
        SELECT last_announced_count
        FROM bonus_announcements
        WHERE contest_id=? AND sport=? AND normalized_player_name=? AND bonus_code=?
        """,
        (777, "GOLF", "Rory McIlroy", "EAG"),
    ).fetchone()
    assert row == (1,)


def test_announce_vip_bonuses_increments_one_message_per_count():
    conn = _build_conn()
    sender = _Sender()
    conn.execute(
        """
        INSERT INTO bonus_announcements (contest_id, sport, normalized_player_name, bonus_code, last_announced_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (777, "GOLF", "Rory McIlroy", "EAG", 1),
    )
    conn.commit()
    vip_lineups = [
        {
            "user": "zeta",
            "players": [
                {"name": "Rory McIlroy", "stats": "22 PAR, 3 EAG", "ownership": 0.347},
            ],
        }
    ]

    sent = announce_vip_bonuses(
        conn=conn,
        sport="GOLF",
        contest_id=777,
        vip_lineups=vip_lineups,
        sender=sender,
    )

    assert sent == 2
    assert sender.messages == [
        "GOLF: Rory McIlroy (34.7%) recorded an eagle (+8 pts, 16 total bonus pts) (VIPs: zeta)",
        "GOLF: Rory McIlroy (34.7%) recorded an eagle (+8 pts, 24 total bonus pts) (VIPs: zeta)",
    ]
    row = conn.execute(
        """
        SELECT last_announced_count
        FROM bonus_announcements
        WHERE contest_id=? AND sport=? AND normalized_player_name=? AND bonus_code=?
        """,
        (777, "GOLF", "Rory McIlroy", "EAG"),
    ).fetchone()
    assert row == (3,)


def test_announce_vip_bonuses_sorts_and_caps_vip_names():
    conn = _build_conn()
    sender = _Sender()
    vip_lineups = []
    for vip_name in ["zoe", "amy", "mike", "beth", "carl", "dana"]:
        vip_lineups.append(
            {
                "user": vip_name,
                "players": [{"name": "Rory McIlroy", "stats": "2 EAG"}],
            }
        )

    sent = announce_vip_bonuses(
        conn=conn,
        sport="GOLF",
        contest_id=555,
        vip_lineups=vip_lineups,
        sender=sender,
    )
    assert sent == 2
    assert sender.messages
    assert "VIPs: amy, beth, carl, dana, mike +1 more" in sender.messages[0]


def test_announce_vip_bonuses_uses_deterministic_canonical_display_name():
    conn = _build_conn()
    sender = _Sender()
    vip_lineups = [
        {
            "user": "amy",
            "players": [{"name": "José Alvarado", "stats": "1 EAG", "ownership": 0.101}],
        },
        {
            "user": "beth",
            "players": [{"name": "Jose Alvarado", "stats": "1 EAG", "ownership": 0.203}],
        },
    ]

    sent = announce_vip_bonuses(
        conn=conn,
        sport="GOLF",
        contest_id=556,
        vip_lineups=vip_lineups,
        sender=sender,
    )

    assert sent == 1
    assert sender.messages
    assert "Jose Alvarado (20.3%)" in sender.messages[0]


def test_announce_vip_bonuses_nba_binary_points_message():
    conn = _build_conn()
    sender = _Sender()
    vip_lineups = [
        {
            "user": "amy",
            "players": [
                {
                    "name": "Nikola Jokic",
                    "stats": "10 REB, 12 AST, 28 PTS, 1 TDbl",
                    "ownership": 0.347,
                }
            ],
        }
    ]
    sent = announce_vip_bonuses(
        conn=conn,
        sport="NBA",
        contest_id=1001,
        vip_lineups=vip_lineups,
        sender=sender,
    )

    assert sent == 1
    assert sender.messages == ["NBA: Nikola Jokic (34.7%) achieved a triple-double (+3 pts) (VIPs: amy)"]


def test_announce_vip_bonuses_webhook_failure_does_not_update_db():
    conn = _build_conn()
    sender = _Sender()
    sender.raise_error = True
    vip_lineups = [
        {
            "user": "amy",
            "players": [{"name": "Rory McIlroy", "stats": "1 EAG"}],
        }
    ]

    sent = announce_vip_bonuses(
        conn=conn,
        sport="GOLF",
        contest_id=888,
        vip_lineups=vip_lineups,
        sender=sender,
    )
    assert sent == 0
    row = conn.execute(
        """
        SELECT last_announced_count
        FROM bonus_announcements
        WHERE contest_id=? AND sport=? AND normalized_player_name=? AND bonus_code=?
        """,
        (888, "GOLF", "Rory McIlroy", "EAG"),
    ).fetchone()
    assert row is None


def test_announce_vip_bonuses_cas_rowcount_zero_skips_update(monkeypatch):
    conn = _build_conn()
    sender = _Sender()
    conn.execute(
        """
        INSERT INTO bonus_announcements (contest_id, sport, normalized_player_name, bonus_code, last_announced_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (999, "GOLF", "Rory McIlroy", "EAG", 1),
    )
    conn.commit()
    monkeypatch.setattr(
        bonus_announcements._SqliteBonusStateStore,
        "compare_and_set",
        lambda *_a, **_k: False,
    )
    vip_lineups = [
        {
            "user": "amy",
            "players": [{"name": "Rory McIlroy", "stats": "2 EAG"}],
        }
    ]
    sent = announce_vip_bonuses(
        conn=conn,
        sport="GOLF",
        contest_id=999,
        vip_lineups=vip_lineups,
        sender=sender,
    )
    assert sent == 0
    assert sender.messages == ["GOLF: Rory McIlroy (0.0%) recorded an eagle (+8 pts, 16 total bonus pts) (VIPs: amy)"]
    row = conn.execute(
        """
        SELECT last_announced_count
        FROM bonus_announcements
        WHERE contest_id=? AND sport=? AND normalized_player_name=? AND bonus_code=?
        """,
        (999, "GOLF", "Rory McIlroy", "EAG"),
    ).fetchone()
    assert row == (1,)


def test_announce_vip_bonuses_soc_goal_message():
    conn = _build_conn()
    sender = _Sender()
    vip_lineups = [
        {
            "user": "amy",
            "players": [
                {
                    "name": "Erling Haaland",
                    "stats": "1 G, 0 A, 2 SOG",
                    "ownership": 0.285,
                }
            ],
        }
    ]
    sent = announce_vip_bonuses(
        conn=conn,
        sport="SOC",
        contest_id=2001,
        vip_lineups=vip_lineups,
        sender=sender,
    )

    assert sent == 1
    assert sender.messages == ["SOC: Erling Haaland (28.5%) scored a goal (+8 pts) (VIPs: amy)"]


def test_announce_vip_bonuses_soc_two_goals_sends_two_messages():
    conn = _build_conn()
    sender = _Sender()
    vip_lineups = [
        {
            "user": "amy",
            "players": [
                {
                    "name": "Erling Haaland",
                    "stats": "2 G, 1 A, 3 SOG",
                    "ownership": 0.285,
                }
            ],
        }
    ]
    sent = announce_vip_bonuses(
        conn=conn,
        sport="SOC",
        contest_id=2002,
        vip_lineups=vip_lineups,
        sender=sender,
    )

    assert sent == 2
    assert sender.messages == [
        "SOC: Erling Haaland (28.5%) scored a goal (+8 pts) (VIPs: amy)",
        "SOC: Erling Haaland (28.5%) scored a goal (+8 pts, 16 total bonus pts) (VIPs: amy)",
    ]


def test_announce_logs_structured_events(caplog):
    import logging

    conn = _build_conn()
    sender = _Sender()
    vip_lineups = [
        {
            "user": "zeta",
            "players": [
                {"name": "Rory McIlroy", "stats": "22 PAR, 1 EAG", "ownership": 0.347},
            ],
        }
    ]
    with caplog.at_level(logging.DEBUG):
        announce_vip_bonuses(
            conn=conn,
            sport="GOLF",
            contest_id=777,
            vip_lineups=vip_lineups,
            sender=sender,
        )
    messages = [r.message for r in caplog.records]
    assert any(m.startswith("vip_bonus_start") for m in messages)
    assert any(m.startswith("vip_bonus_complete") for m in messages)
    assert not any("Starting VIP bonus" in m for m in messages)
    assert not any("Completed VIP bonus" in m for m in messages)
    candidates_msgs = [m for m in messages if "vip_bonus_candidates" in m]
    assert not any("{'EAG" in m or "{'BIR" in m for m in candidates_msgs)
