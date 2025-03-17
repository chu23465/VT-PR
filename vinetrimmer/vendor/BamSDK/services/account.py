from requests import Request

from vinetrimmer.vendor.BamSDK.services import Service


# noinspection PyPep8Naming
class account(Service):
    def createAccountGrant(self, json, access_token):
        endpoint = self.client.endpoints["createAccountGrant"]
        req = Request(
            method=endpoint.method,
            url=endpoint.href,
            headers=endpoint.get_headers(accessToken=access_token),
            json=json
        ).prepare()
        res = self.session.send(req)
        return res.json()

    def getUserProfiles(self, access_token):
        endpoint = self.client.endpoints["getUserProfiles"]
        req = Request(
            method=endpoint.method,
            url=endpoint.href,
            headers=endpoint.get_headers(accessToken=access_token)
        ).prepare()
        res = self.session.send(req)
        return res.json()

    def setActiveUserProfile(self, profile_id, access_token):
        endpoint = self.client.endpoints["setActiveUserProfile"]
        req = Request(
            method=endpoint.method,
            url=endpoint.href.format(profileId=profile_id),
            headers=endpoint.get_headers(accessToken=access_token)
        ).prepare()
        res = self.session.send(req)
        return res.json()
