from typing import Any, Callable


class BotInterface:
    """Interface for chat bot senders used by this repo."""

    def __init__(self, bot_id: Any) -> None:
        self.bot_id = bot_id

    def send_message(self, message: str) -> None:
        """Send a message to the chat backend (implemented by subclasses)."""
        raise NotImplementedError("A send message method has not been implemented")

    def send(self, callback: Callable[..., str], *args: Any) -> None:
        """Invoke a callback to build a message, then send it."""
        try:
            message = callback(*args)
        except Exception as err:
            message = "There was an error that occurred with the bot: {}\n\n".format(err)
            message += "Please report it at https://github.com/SwapnikKatkoori/sleeper-ff-bot/issues"
        self.send_message(message)
