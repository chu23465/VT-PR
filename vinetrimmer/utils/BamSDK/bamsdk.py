import requests

from vinetrimmer.utils.BamSDK.services.account import account
from vinetrimmer.utils.BamSDK.services.bamIdentity import bamIdentity
from vinetrimmer.utils.BamSDK.services.content import content
from vinetrimmer.utils.BamSDK.services.device import device
from vinetrimmer.utils.BamSDK.services.drm import drm
from vinetrimmer.utils.BamSDK.services.media import media
from vinetrimmer.utils.BamSDK.services.session import session
from vinetrimmer.utils.BamSDK.services.token import token


class BamSdk:
    def __init__(self, endpoint, session_=None):
        self._session = session_ or requests.Session()

        self.config = self._session.get(endpoint).json()
        self.application = self.config["application"]
        self.commonHeaders = self.config["commonHeaders"]

        self.account = account(self.config["services"]["account"], self._session)
        self.bamIdentity = bamIdentity(self.config["services"]["bamIdentity"], self._session)
        self.content = content(self.config["services"]["content"], self._session)
        self.device = device(self.config["services"]["device"], self._session)
        self.drm = drm(self.config["services"]["drm"], self._session)
        self.media = media(self.config["services"]["media"], self._session)
        self.session = session(self.config["services"]["session"], self._session)
        self.token = token(self.config["services"]["token"], self._session)
