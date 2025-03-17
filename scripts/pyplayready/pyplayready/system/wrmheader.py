import base64
import binascii
from enum import Enum
from typing import Optional, List, Union, Tuple

import xmltodict


class WRMHeader:
    """Represents a PlayReady WRM Header"""

    class SignedKeyID:
        def __init__(
                self,
                alg_id: str,
                value: str,
                checksum: str
        ):
            self.alg_id = alg_id
            self.value = value
            self.checksum = checksum

        def __repr__(self):
            return f'SignedKeyID(alg_id={self.alg_id}, value="{self.value}", checksum="{self.checksum}")'

    class Version(Enum):
        VERSION_4_0_0_0 = "4.0.0.0"
        VERSION_4_1_0_0 = "4.1.0.0"
        VERSION_4_2_0_0 = "4.2.0.0"
        VERSION_4_3_0_0 = "4.3.0.0"
        UNKNOWN = "UNKNOWN"

        @classmethod
        def _missing_(cls, value):
            return cls.UNKNOWN

    _RETURN_STRUCTURE = Tuple[List[SignedKeyID], Union[str, None], Union[str, None], Union[str, None]]

    def __init__(self, data: Union[str, bytes]):
        """Load a WRM Header from either a string, base64 encoded data or bytes"""

        if not data:
            raise ValueError("Data must not be empty")

        if isinstance(data, str):
            try:
                data = base64.b64decode(data).decode()
            except (binascii.Error, binascii.Incomplete):
                data = data.encode()

        self._raw_data: bytes = data
        self._parsed = xmltodict.parse(self._raw_data)

        self._header = self._parsed.get('WRMHEADER')
        if not self._header:
            raise ValueError("Data is not a valid WRMHEADER")

        self.version = self.Version(self._header.get('@version'))

    @staticmethod
    def _ensure_list(element: Union[dict, list]) -> List:
        if isinstance(element, dict):
            return [element]
        return element

    @staticmethod
    def _read_v4_0_0_0(data: dict) -> _RETURN_STRUCTURE:
        protect_info = data.get("PROTECTINFO")

        return (
            [WRMHeader.SignedKeyID(
                alg_id=protect_info["ALGID"],
                value=data["KID"],
                checksum=data.get("CHECKSUM")
            )],
            data.get("LA_URL"),
            data.get("LUI_URL"),
            data.get("DS_ID")
        )

    @staticmethod
    def _read_v4_1_0_0(data: dict) -> _RETURN_STRUCTURE:
        protect_info = data.get("PROTECTINFO")

        key_ids = []
        if protect_info:
            kid = protect_info["KID"]
            if kid:
                key_ids = [WRMHeader.SignedKeyID(
                    alg_id=kid["@ALGID"],
                    value=kid["@VALUE"],
                    checksum=kid.get("@CHECKSUM")
                )]

        return (
            key_ids,
            data.get("LA_URL"),
            data.get("LUI_URL"),
            data.get("DS_ID")
        )

    @staticmethod
    def _read_v4_2_0_0(data: dict) -> _RETURN_STRUCTURE:
        protect_info = data.get("PROTECTINFO")

        key_ids = []
        if protect_info:
            kids = protect_info["KIDS"]
            if kids:
                for kid in WRMHeader._ensure_list(kids["KID"]):
                    key_ids.append(WRMHeader.SignedKeyID(
                        alg_id=kid["@ALGID"],
                        value=kid["@VALUE"],
                        checksum=kid.get("@CHECKSUM")
                    ))

        return (
            key_ids,
            data.get("LA_URL"),
            data.get("LUI_URL"),
            data.get("DS_ID")
        )

    @staticmethod
    def _read_v4_3_0_0(data: dict) -> _RETURN_STRUCTURE:
        protect_info = data.get("PROTECTINFO")

        key_ids = []
        if protect_info:
            kids = protect_info["KIDS"]
            for kid in WRMHeader._ensure_list(kids["KID"]):
                key_ids.append(WRMHeader.SignedKeyID(
                    alg_id=kid.get("@ALGID"),
                    value=kid["@VALUE"],
                    checksum=kid.get("@CHECKSUM")
                ))

        return (
            key_ids,
            data.get("LA_URL"),
            data.get("LUI_URL"),
            data.get("DS_ID")
        )

    def read_attributes(self) -> _RETURN_STRUCTURE:
        """
        Read any non-custom XML attributes

        Returns a tuple structured like this: Tuple[List[SignedKeyID], <LA_URL>, <LUI_URL>, <DS_ID>]
        """
        data = self._header.get("DATA")
        if not data:
            raise ValueError("Not a valid PlayReady Header Record, WRMHEADER/DATA required")

        if self.version == self.Version.VERSION_4_0_0_0:
            return self._read_v4_0_0_0(data)
        elif self.version == self.Version.VERSION_4_1_0_0:
            return self._read_v4_1_0_0(data)
        elif self.version == self.Version.VERSION_4_2_0_0:
            return self._read_v4_2_0_0(data)
        elif self.version == self.Version.VERSION_4_3_0_0:
            return self._read_v4_3_0_0(data)

    def dumps(self) -> str:
        return self._raw_data.decode("utf-16-le")
