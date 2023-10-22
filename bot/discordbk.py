import requests
import json
import logging
from .botinterface import BotInterface


class Discord(BotInterface):
    def __init__(self, webhook):
        self.webhook = webhook
        #self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.76 Safari/537.36'}
        #self.headers = {'Content-Type': 'application/json'}
        self.headers = {
            'Content-Type': 'application/json',
            'Cookie': '__cfruid=7ee6f18609e42e313bf0cd2da38d8ef8346c1469-1696086952; __dcfduid=3ed93d485fa411ee8f140aa9c816f638; __sdcfduid=3ed93d485fa411ee8f140aa9c816f638b18dc08933227bef6be85c3535df1861b6e3fff3b2374b60d5f293b18375be9f'
        }


    def send_message(self, message):
        # These two lines enable debugging at httplib level (requests->urllib3->http.client)
        # You will see the REQUEST, including HEADERS and DATA, and RESPONSE with HEADERS but without DATA.
        # The only thing missing will be the response.body which is not logged.
        try:
            import http.client as http_client
        except ImportError:
            # Python 2
            import httplib as http_client
        http_client.HTTPConnection.debuglevel = 1
         # You must initialize logging, otherwise you'll not see debug output.
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True
        print(self.webhook)
        j = {"content": message}
        print(j)
        payload = json.dumps(j)
        #requests.post(self.webhook, json=json, headers=self.headers)
        #requests.request("POST", self.webhook, headers=self.headers, data=payload)
        url = "https://discord.com/api/webhooks/1030903662270238851/9ir7Xm1s4YGtVGA-t6YylyBznNgGWXSnhvD8tdDtMToM2jhELHAsU_xkKrvHf4EDcRiz"
        print(url)
        print(self.webhook)

        payload = json.dumps({
            "content": "testy test"
        })
        headers = {
                  'Content-Type': 'application/json',
                    'Cookie': '__cfruid=7ee6f18609e42e313bf0cd2da38d8ef8346c1469-1696086952; __dcfduid=3ed93d485fa411ee8f140aa9c816f638; __sdcfduid=3ed93d485fa411ee8f140aa9c816f638b18dc08933227bef6be85c3535df1861b6e3fff3b2374b60d5f293b18375be9f'
                    }

        response = requests.request("POST", self.webhook, headers=headers, data=payload)

