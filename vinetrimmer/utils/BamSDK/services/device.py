from json import JSONDecodeError

from requests import Request

from vinetrimmer.utils.BamSDK.services import Service


# noinspection PyPep8Naming
class device(Service):

    def createDeviceGrant(self, json, api_key):
        endpoint = self.client.endpoints["createDeviceGrant"]
        req = Request(
            method=endpoint.method,
            url=endpoint.href,
            headers=endpoint.get_headers(apiKey=api_key),
            json=json
        ).prepare()
        res = self.session.send(req)
        try:
            data = res.json()
        except JSONDecodeError:
            raise Exception(f"An unexpected response occurred for bamsdk.createDeviceGrant: {res.text}")
        return data
