import requests


class Service:
    def __init__(self, cfg, session=None):
        self.session = session or requests.Session()
        self.client = Client(cfg.get("client") or {})
        self.disabled = cfg.get("disabled")
        self.extras = cfg.get("extras")


class Client:
    def __init__(self, data):
        self.baseUrl = data.get("baseUrl")
        self.endpoints = {k: Endpoint(v) for k, v in (data.get("endpoints") or {}).items()}
        self.extras = data.get("extras") or {}


class Endpoint:
    def __init__(self, data):
        self.headers = data.get("headers") or {}
        self.href = data["href"]
        self.method = data.get("method") or "GET"
        self.templated = data.get("templated") or False
        self.timeout = data.get("timeout") or 15
        self.ttl = data.get("ttl") or 0

    # noinspection PyPep8Naming
    def get_headers(self, accessToken=None, apiKey=None):
        token = None
        if accessToken:
            token = {"accessToken": accessToken}
        elif apiKey:
            token = {"apiKey": apiKey}
        if token:
            self.headers.update({"Authorization": self.headers["Authorization"].format(**token)})
        return self.headers
