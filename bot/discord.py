import requests

from .botinterface import BotInterface


class Discord(BotInterface):
    """Webhook-based Discord sender."""

    def __init__(self, webhook: str) -> None:
        self.webhook = webhook

    def send_message(self, message: str) -> None:
        """Post a message to the configured webhook."""
        payload = {"content": message}
        requests.post(self.webhook, json=payload)
