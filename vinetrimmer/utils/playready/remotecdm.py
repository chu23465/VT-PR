from __future__ import annotations

import re

import requests

from .cdm import Cdm
from .device import Device
from .key import Key

from .exceptions import (DeviceMismatch, InvalidInitData)


class RemoteCdm(Cdm):
    """Remote Accessible CDM using pyplayready's serve schema."""

    def __init__(
        self,
        security_level: int,
        host: str,
        secret: str,
        device_name: str
    ):
        """Initialize a Playready Content Decryption Module (CDM)."""
        if not security_level:
            raise ValueError("Security Level must be provided")
        if not isinstance(security_level, int):
            raise TypeError(f"Expected security_level to be a {int} not {security_level!r}")

        if not host:
            raise ValueError("API Host must be provided")
        if not isinstance(host, str):
            raise TypeError(f"Expected host to be a {str} not {host!r}")

        if not secret:
            raise ValueError("API Secret must be provided")
        if not isinstance(secret, str):
            raise TypeError(f"Expected secret to be a {str} not {secret!r}")

        if not device_name:
            raise ValueError("API Device name must be provided")
        if not isinstance(device_name, str):
            raise TypeError(f"Expected device_name to be a {str} not {device_name!r}")

        self.security_level = security_level
        self.host = host
        self.device_name = device_name

        # spoof certificate_chain and ecc_key just so we can construct via super call
        super().__init__(security_level, None, None, None)

        self.__session = requests.Session()
        self.__session.headers.update({
            "X-Secret-Key": secret
        })

        r = requests.head(self.host)
        if r.status_code != 200:
            raise ValueError(f"Could not test Remote API version [{r.status_code}]")
        server = r.headers.get("Server")
        if not server or "pyplayready serve" not in server.lower():
            raise ValueError(f"This Remote CDM API does not seem to be a pyplayready serve API ({server}).")
        server_version_re = re.search(r"pyplayready serve v([\d.]+)", server, re.IGNORECASE)
        if not server_version_re:
            raise ValueError("The pyplayready server API is not stating the version correctly, cannot continue.")
        server_version = server_version_re.group(1)
        if server_version < "0.3.1":
            raise ValueError(f"This pyplayready serve API version ({server_version}) is not supported.")

    @classmethod
    def from_device(cls, device: Device) -> RemoteCdm:
        raise NotImplementedError("You cannot load a RemoteCdm from a local Device file.")

    def open(self) -> bytes:
        r = self.__session.get(
            url=f"{self.host}/{self.device_name}/open"
        ).json()

        if r['status'] != 200:
            raise ValueError(f"Cannot Open CDM Session, {r['message']} [{r['status']}]")
        r = r["data"]

        if int(r["device"]["security_level"]) != self.security_level:
            raise DeviceMismatch("The Security Level specified does not match the one specified in the API response.")

        return bytes.fromhex(r["session_id"])

    def close(self, session_id: bytes) -> None:
        r = self.__session.get(
            url=f"{self.host}/{self.device_name}/close/{session_id.hex()}"
        ).json()
        if r["status"] != 200:
            raise ValueError(f"Cannot Close CDM Session, {r['message']} [{r['status']}]")

    def get_license_challenge(
        self,
        session_id: bytes,
        wrm_header: str,
    ) -> str:
        if not wrm_header:
            raise InvalidInitData("A wrm_header must be provided.")
        if not isinstance(wrm_header, str):
            raise InvalidInitData(f"Expected wrm_header to be a {str}, not {wrm_header!r}")

        r = self.__session.post(
            url=f"{self.host}/{self.device_name}/get_license_challenge",
            json={
                "session_id": session_id.hex(),
                "init_data": wrm_header,
            }
        ).json()
        if r["status"] != 200:
            raise ValueError(f"Cannot get Challenge, {r['message']} [{r['status']}]")
        r = r["data"]

        return r["challenge"]

    def parse_license(self, session_id: bytes, license_message: str) -> None:
        if not license_message:
            raise Exception("Cannot parse an empty license_message")

        if not isinstance(license_message, str):
            raise Exception(f"Expected license_message to be a {str}, not {license_message!r}")

        r = self.__session.post(
            url=f"{self.host}/{self.device_name}/parse_license",
            json={
                "session_id": session_id.hex(),
                "license_message": license_message
            }
        ).json()
        if r["status"] != 200:
            raise ValueError(f"Cannot parse License, {r['message']} [{r['status']}]")

    def get_keys(self, session_id: bytes) -> list[Key]:
        r = self.__session.post(
            url=f"{self.host}/{self.device_name}/get_keys",
            json={
                "session_id": session_id.hex()
            }
        ).json()
        if r["status"] != 200:
            raise ValueError(f"Could not get Keys, {r['message']} [{r['status']}]")
        r = r["data"]

        return [
            Key(
                key_type=key["type"],
                key_id=Key.kid_to_uuid(bytes.fromhex(key["key_id"])),
                key=bytes.fromhex(key["key"]),
                cipher_type=key["cipher_type"],
                key_length=key["key_length"]
            )
            for key in r["keys"]
        ]


__all__ = ("RemoteCdm",)
