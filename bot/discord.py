import requests
from .botinterface import BotInterface


class Discord(BotInterface):
    def __init__(self, webhook):
        self.webhook = webhook

    def send_message(self, message):
        requests.post(self.webhook, json={"content": message})
