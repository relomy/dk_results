import sqlite3

import classes.bonus_announcements as bonus_announcements
from classes.bonus_announcements import (
    announce_vip_bonuses,
    create_bonus_announcements_table,
)


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
    create_bonus_announcements_table(conn)
    return conn


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
    assert (
        sender.messages[0]
        == "GOLF: Rory McIlroy (34.7%) recorded an eagle (+8 pts) (VIPs: zeta)"
    )
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
    assert sender.messages == [
        "NBA: Nikola Jokic (34.7%) achieved a triple-double (+3 pts) (VIPs: amy)"
    ]


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
    monkeypatch.setattr(bonus_announcements, "_cas_update_count", lambda *_a, **_k: False)
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
    assert sender.messages == [
        "GOLF: Rory McIlroy (0.0%) recorded an eagle (+8 pts, 16 total bonus pts) (VIPs: amy)"
    ]
    row = conn.execute(
        """
        SELECT last_announced_count
        FROM bonus_announcements
        WHERE contest_id=? AND sport=? AND normalized_player_name=? AND bonus_code=?
        """,
        (999, "GOLF", "Rory McIlroy", "EAG"),
    ).fetchone()
    assert row == (1,)
