import pytest

from bot.botinterface import BotInterface


class DummyBot(BotInterface):
    def __init__(self, bot_id="bot") -> None:
        super().__init__(bot_id)
        self.sent: list[str] = []

    def send_message(self, message: str) -> None:
        self.sent.append(message)


def test_send_message_raises():
    bot = BotInterface("id")
    with pytest.raises(NotImplementedError):
        bot.send_message("hi")


def test_send_passes_message():
    bot = DummyBot()
    bot.send(lambda name: f"hello {name}", "world")
    assert bot.sent == ["hello world"]


def test_send_handles_callback_error():
    bot = DummyBot()

    def boom():
        raise ValueError("boom")

    bot.send(boom)

    assert bot.sent
    assert "There was an error that occurred with the bot: boom" in bot.sent[0]
    assert (
        "Please report it at https://github.com/SwapnikKatkoori/sleeper-ff-bot/issues"
        in bot.sent[0]
    )
