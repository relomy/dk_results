from bot.webhook import DiscordWebhook
from dfs_common import discord as common_discord


def test_webhook_send_message(monkeypatch):
    captured = {}

    def fake_send(self, message):
        captured["message"] = message

    monkeypatch.setattr(common_discord.WebhookSender, "send_message", fake_send)

    webhook = DiscordWebhook("https://example.test/hook")
    webhook.send_message("ping")

    assert captured["message"] == "ping"
