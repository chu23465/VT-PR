from __future__ import annotations

import base64
from pathlib import Path
from typing import Union

from Crypto.Hash import SHA256
from Crypto.PublicKey import ECC
from Crypto.PublicKey.ECC import EccKey
from ecpy.curves import Curve, Point


class ECCKey:
    """Represents a PlayReady ECC key pair"""

    def __init__(self, key: EccKey):
        self.key = key

    @classmethod
    def generate(cls):
        """Generate a new ECC key pair"""
        return cls(key=ECC.generate(curve='P-256'))

    @classmethod
    def construct(cls, private_key: Union[bytes, int]):
        """Construct an ECC key pair from private/public bytes/ints"""
        if isinstance(private_key, bytes):
            private_key = int.from_bytes(private_key, 'big')
        if not isinstance(private_key, int):
            raise ValueError(f"Expecting Bytes or Int input, got {private_key!r}")

        # The public is always derived from the private key; loading the other stuff won't work
        key = ECC.construct(
            curve='P-256',
            d=private_key,
        )

        return cls(key=key)

    @classmethod
    def loads(cls, data: Union[str, bytes]) -> ECCKey:
        if isinstance(data, str):
            data = base64.b64decode(data)
        if not isinstance(data, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {data!r}")

        if len(data) not in [96, 32]:
            raise ValueError(f"Invalid data length. Expecting 96 or 32 bytes, got {len(data)}")

        return cls.construct(private_key=data[:32])

    @classmethod
    def load(cls, path: Union[Path, str]) -> ECCKey:
        if not isinstance(path, (Path, str)):
            raise ValueError(f"Expecting Path object or path string, got {path!r}")
        with Path(path).open(mode="rb") as f:
            return cls.loads(f.read())

    def dumps(self, private_only=False):
        if private_only:
            return self.private_bytes()
        return self.private_bytes() + self.public_bytes()

    def dump(self, path: Union[Path, str], private_only=False) -> None:
        if not isinstance(path, (Path, str)):
            raise ValueError(f"Expecting Path object or path string, got {path!r}")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.dumps(private_only))

    @staticmethod
    def _to_bytes(n: int) -> bytes:
        byte_len = (n.bit_length() + 7) // 8
        if byte_len % 2 != 0:
            byte_len += 1
        return n.to_bytes(byte_len, 'big')

    def get_point(self, curve: Curve) -> Point:
        return Point(self.key.pointQ.x, self.key.pointQ.y, curve)

    def private_bytes(self) -> bytes:
        return self._to_bytes(int(self.key.d))

    def private_sha256_digest(self) -> bytes:
        hash_object = SHA256.new()
        hash_object.update(self.private_bytes())
        return hash_object.digest()

    def public_bytes(self) -> bytes:
        return self._to_bytes(int(self.key.pointQ.x)) + self._to_bytes(int(self.key.pointQ.y))

    def public_sha256_digest(self) -> bytes:
        hash_object = SHA256.new()
        hash_object.update(self.public_bytes())
        return hash_object.digest()
