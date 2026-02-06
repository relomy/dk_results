from bot.discord_rest import DiscordRest


def test_send_message_posts(monkeypatch):
    captured = {}

    def fake_post(url, json, headers):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers

    monkeypatch.setattr("bot.discord_rest.requests.post", fake_post)

    client = DiscordRest("tok", 123)
    client.send_message("hello")

    assert captured["url"] == "https://discord.com/api/v10/channels/123/messages"
    assert captured["json"] == {"content": "hello"}
    assert captured["headers"] == {"Authorization": "Bot tok"}
