import requests


class DiscordRest:
    """Minimal REST client for posting messages to a Discord channel."""

    def __init__(self, token: str, channel_id: int) -> None:
        self.token = token
        self.channel_id = channel_id

    def send_message(self, message: str) -> None:
        """Post a message to the configured channel."""
        url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}"}
        payload = {"content": message}
        requests.post(url, json=payload, headers=headers)
