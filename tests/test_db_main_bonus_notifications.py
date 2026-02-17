import dk_results.cli.db_main as db_main


def test_build_bonus_sender_respects_notifications_enabled(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK", "https://example.test/webhook")
    monkeypatch.setenv("DISCORD_NOTIFICATIONS_ENABLED", "false")

    assert db_main._build_bonus_sender() is None
