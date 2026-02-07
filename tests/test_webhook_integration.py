from bot.discord import Discord
from dfs_common import discord as common_discord


def test_discord_uses_webhook_sender(monkeypatch):
    calls = {}

    def fake_send(self, message):
        calls["message"] = message

    monkeypatch.setattr(common_discord.WebhookSender, "send_message", fake_send)

    bot = Discord("http://example")
    bot.send_message("hi")

    assert calls["message"] == "hi"
