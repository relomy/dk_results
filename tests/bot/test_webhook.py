from bot.webhook import DiscordWebhook


def test_webhook_send_message(monkeypatch):
    captured = {}

    def fake_post(url, json):
        captured["url"] = url
        captured["json"] = json

    monkeypatch.setattr("bot.webhook.requests.post", fake_post)

    webhook = DiscordWebhook("https://example.test/hook")
    webhook.send_message("ping")

    assert captured == {
        "url": "https://example.test/hook",
        "json": {"content": "ping"},
    }
