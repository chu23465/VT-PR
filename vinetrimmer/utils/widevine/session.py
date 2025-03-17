import base64

from construct import Container

from vinetrimmer.utils.widevine.protos import widevine_pb2 as widevine
from vinetrimmer.vendor.pymp4.parser import Box


class Session:
    def __init__(self, session_id, pssh, raw, offline):
        if not session_id:
            raise ValueError("A session_id must be provided...")
        if not pssh:
            raise ValueError("A PSSH Box must be provided...")
        self.session_id = session_id
        self.pssh = pssh
        self.cenc_header = pssh
        self.offline = offline
        self.raw = raw
        self.session_key = None
        self.derived_keys = {
            "enc": None,
            "auth_1": None,
            "auth_2": None
        }
        self.license_request = None
        self.signed_license = None
        self.signed_device_certificate = None
        self.privacy_mode = False
        self.keys = []

    def __repr__(self):
        return "{name}({items})".format(
            name=self.__class__.__name__,
            items=", ".join([f"{k}={repr(v)}" for k, v in self.__dict__.items()])
        )

    @staticmethod
    def parse_pssh_box(pssh):
        """
        Parse a PSSH box's init_data into a WidevineCencHeader.

        Parameters:
            pssh: A pssh box as str (base64), bytes, or a PSSH Box Container.

        Returns:
            The init_data parsed as a WidevineCencHeader.
        """
        # if isinstance(pssh, str):
            # pssh = base64.b64decode(pssh)
        # if not isinstance(pssh, Container):
            # pssh = Box.parse(pssh)
        # cenc_header = widevine.WidevineCencHeader()
        # cenc_header.ParseFromString(pssh.init_data)
        # return cenc_header
        return False
