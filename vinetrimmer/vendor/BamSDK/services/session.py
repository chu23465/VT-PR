from requests import Request

from vinetrimmer.vendor.BamSDK.services import Service


# noinspection PyPep8Naming
class session(Service):
    def getInfo(self, access_token):
        endpoint = self.client.endpoints["getInfo"]
        req = Request(
            method=endpoint.method,
            url=endpoint.href,
            headers=endpoint.get_headers(accessToken=access_token)
        ).prepare()
        res = self.session.send(req)
        return res.json()

    def getLocation(self, access_token):
        endpoint = self.client.endpoints["getLocation"]
        req = Request(
            method=endpoint.method,
            url=endpoint.href,
            headers=endpoint.get_headers(accessToken=access_token)
        ).prepare()
        res = self.session.send(req)
        return res.json()
