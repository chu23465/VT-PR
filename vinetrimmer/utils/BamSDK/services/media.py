from requests import Request

from vinetrimmer.utils.BamSDK.services import Service


# noinspection PyPep8Naming
class media(Service):
    def __init__(self, cfg, session=None):
        super().__init__(cfg, session)
        self.uhd_allowed = self.extras["isUhdAllowed"]
        self.default_scenario = self.extras["playbackScenarioDefault"]
        self.scenarios = self.extras["playbackScenarios"]
        self.restricted_scenario = self.extras["restrictedPlaybackScenario"]
        self.security_requirements = self.extras["securityCheckRequirements"]

    def mediaPayload(self, media_id, scenario, access_token):
        endpoint = self.client.endpoints["mediaPayload"]
        req = Request(
            method=endpoint.method,
            url=f"{self.client.baseUrl}/media/{media_id}/scenarios/{scenario}",
            headers=endpoint.get_headers(accessToken=access_token)
        ).prepare()
        res = self.session.send(req)
        return res.json()
