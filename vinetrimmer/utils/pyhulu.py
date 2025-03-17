import base64
import hashlib
import logging
import random

import pyhulu


class Device:  # pylint: disable=too-few-public-methods
    """Data class used for containing device attributes."""

    def __init__(self, device_code, device_key):
        self.device_code = str(device_code)

        if isinstance(device_key, str):
            self.device_key = bytes.fromhex(device_key)
        else:
            self.device_key = device_key

        if len(self.device_code) != 3:
            raise ValueError("Invalid device code length")

        if len(self.device_key) != 16:
            raise ValueError("Invalid device key length")

    def __repr__(self):
        return "<Device device_code={}, device_key={}>".format(
            self.device_code,
            base64.b64encode(self.device_key).decode("utf-8")
        )


class HuluClient(pyhulu.HuluClient):
    def __init__(self, device, session, version=1, **kwargs):
        self.logger = logging.getLogger(__name__)
        self.device = device
        self.session = session
        self.version = version or 1
        self.extra_playlist_params = kwargs

        self.session_key, self.server_key = self.get_session_key()

    def load_playlist(self, video_id):
        """
        load_playlist()

        Method to get a playlist containing the MPD
        and license URL for the provided video ID and return it

        @param video_id: String of the video ID to get a playlist for

        @return: Dict of decrypted playlist response
        """
        params = {
            "device_identifier": hashlib.md5().hexdigest().upper(),
            "deejay_device_id": int(self.device.device_code),
            "version": self.version,
            "content_eab_id": video_id,
            "rv": random.randrange(100000, 1000000),
            "kv": self.server_key
        }
        params.update(self.extra_playlist_params)

        r = self.session.post("https://play.hulu.com/v6/playlist", json=params)
        ciphertext = self.__get_ciphertext(r.text, params)

        return self.decrypt_response(self.session_key, ciphertext)

    def get_session_key(self):
        """
        get_session_key()

        Method to do a Hulu config request and calculate
        the session key against device key and current server key

        @return: Session key in bytes, and the config key ID.
        """
        random_value = random.randrange(100000, 1000000)
        nonce = hashlib.md5(",".join([
            self.device.device_key.hex(),
            self.device.device_code,
            str(self.version),
            str(random_value)
        ]).encode("utf-8")).hexdigest()

        payload = {
            "rv": random_value,
            "mozart_version": "1",
            "region": "US",
            "version": self.version,
            "device": self.device.device_code,
            "encrypted_nonce": nonce
        }

        r = self.session.post("https://play.hulu.com/config", data=payload)
        ciphertext = self.__get_ciphertext(r.text, payload)

        config = self.decrypt_response(self.device.device_key, ciphertext)

        derived_key_array = bytearray()
        for device_byte, server_byte in zip(self.device.device_key, bytes.fromhex(config["key"])):
            derived_key_array.append(device_byte ^ server_byte)

        return bytes(derived_key_array), config["key_id"]
