from dfs_common.discord import WebhookSender

from .botinterface import BotInterface


class Discord(BotInterface):
    """Webhook-based Discord sender."""

    def __init__(self, webhook: str) -> None:
        self._sender = WebhookSender(webhook)

    def send_message(self, message: str) -> None:
        """Post a message to the configured webhook."""
        self._sender.send_message(message)
