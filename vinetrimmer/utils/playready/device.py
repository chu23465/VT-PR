from __future__ import annotations

import base64
from enum import IntEnum
from pathlib import Path
from typing import Union, Any

from construct import Struct, Const, Int8ub, Bytes, this, Int32ub

from .bcert import CertificateChain
from .ecc_key import ECCKey


class SecurityLevel(IntEnum):
    SL150 = 150
    SL2000 = 2000
    SL3000 = 3000


class _DeviceStructs:
    magic = Const(b"PRD")

    header = Struct(
        "signature" / magic,
        "version" / Int8ub,
    )

    # was never in production
    v1 = Struct(
        "signature" / magic,
        "version" / Int8ub,
        "group_key_length" / Int32ub,
        "group_key" / Bytes(this.group_key_length),
        "group_certificate_length" / Int32ub,
        "group_certificate" / Bytes(this.group_certificate_length)
    )

    v2 = Struct(
        "signature" / magic,
        "version" / Int8ub,
        "group_certificate_length" / Int32ub,
        "group_certificate" / Bytes(this.group_certificate_length),
        "encryption_key" / Bytes(96),
        "signing_key" / Bytes(96),
    )

    v3 = Struct(
        "signature" / magic,
        "version" / Int8ub,
        "group_key" / Bytes(96),
        "encryption_key" / Bytes(96),
        "signing_key" / Bytes(96),
        "group_certificate_length" / Int32ub,
        "group_certificate" / Bytes(this.group_certificate_length),
    )


class Device:
    """Represents a PlayReady Device (.prd)"""
    CURRENT_STRUCT = _DeviceStructs.v3
    CURRENT_VERSION = 3

    def __init__(
            self,
            *_: Any,
            group_key: Union[str, bytes, None],
            encryption_key: Union[str, bytes],
            signing_key: Union[str, bytes],
            group_certificate: Union[str, bytes],
            **__: Any
    ):
        if isinstance(group_key, str):
            group_key = base64.b64decode(group_key)

        if isinstance(encryption_key, str):
            encryption_key = base64.b64decode(encryption_key)
        if not isinstance(encryption_key, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {encryption_key!r}")

        if isinstance(signing_key, str):
            signing_key = base64.b64decode(signing_key)
        if not isinstance(signing_key, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {signing_key!r}")

        if isinstance(group_certificate, str):
            group_certificate = base64.b64decode(group_certificate)
        if not isinstance(group_certificate, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {group_certificate!r}")

        self.group_key = None if group_key is None else ECCKey.loads(group_key)
        self.encryption_key = ECCKey.loads(encryption_key)
        self.signing_key = ECCKey.loads(signing_key)
        self.group_certificate = CertificateChain.loads(group_certificate)
        self.security_level = self.group_certificate.get_security_level()

    @classmethod
    def loads(cls, data: Union[str, bytes]) -> Device:
        if isinstance(data, str):
            data = base64.b64decode(data)
        if not isinstance(data, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {data!r}")

        prd_header = _DeviceStructs.header.parse(data)
        if prd_header.version == 2:
            return cls(
                group_key=None,
                **_DeviceStructs.v2.parse(data)
            )

        return cls(**cls.CURRENT_STRUCT.parse(data))

    @classmethod
    def load(cls, path: Union[Path, str]) -> Device:
        if not isinstance(path, (Path, str)):
            raise ValueError(f"Expecting Path object or path string, got {path!r}")
        with Path(path).open(mode="rb") as f:
            return cls.loads(f.read())

    def dumps(self) -> bytes:
        return self.CURRENT_STRUCT.build(dict(
            version=self.CURRENT_VERSION,
            group_key=self.group_key.dumps(),
            encryption_key=self.encryption_key.dumps(),
            signing_key=self.signing_key.dumps(),
            group_certificate_length=len(self.group_certificate.dumps()),
            group_certificate=self.group_certificate.dumps(),
        ))

    def dump(self, path: Union[Path, str]) -> None:
        if not isinstance(path, (Path, str)):
            raise ValueError(f"Expecting Path object or path string, got {path!r}")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.dumps())

    def get_name(self) -> str:
        name = f"{self.group_certificate.get_name()}_sl{self.group_certificate.get_security_level()}"
        return ''.join(char for char in name if (char.isalnum() or char in '_- ')).strip().lower().replace(" ", "_")
