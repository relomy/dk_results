import pytest
import requests

from dk_results.bot.discord_rest import DiscordRest


def test_send_message_posts(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout

    monkeypatch.setattr("dk_results.bot.discord_rest.requests.post", fake_post)

    client = DiscordRest("tok", 123)
    client.send_message("hello")

    assert captured["url"] == "https://discord.com/api/v10/channels/123/messages"
    assert captured["json"] == {"content": "hello"}
    assert captured["headers"] == {"Authorization": "Bot tok"}
    assert captured["timeout"] == 15


def test_send_message_propagates_timeout(monkeypatch):
    def fake_post(url, json, headers, timeout):
        raise requests.Timeout("slow")

    monkeypatch.setattr("dk_results.bot.discord_rest.requests.post", fake_post)

    with pytest.raises(requests.Timeout):
        DiscordRest("tok", 123).send_message("hello")
