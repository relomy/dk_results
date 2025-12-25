import requests

from .botinterface import BotInterface


class DiscordWebhook(BotInterface):
    def __init__(self, webhook):
        self.webhook = webhook

    def send_message(self, message):
        payload = {"content": message}
        requests.post(self.webhook, json=payload)
