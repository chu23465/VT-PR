import base64
from enum import Enum
from uuid import UUID
from typing import Union


class Key:
    class KeyType(Enum):
        INVALID = 0x0000
        AES_128_CTR = 0x0001
        RC4_CIPHER = 0x0002
        AES_128_ECB = 0x0003
        COCKTAIL = 0x0004
        AES_128_CBC = 0x0005
        KEYEXCHANGE = 0x0006
        UNKNOWN = 0xffff

        @classmethod
        def _missing_(cls, value):
            return cls.UNKNOWN

    class CipherType(Enum):
        INVALID = 0x0000
        RSA_1024 = 0x0001
        CHAINED_LICENSE = 0x0002
        ECC_256 = 0x0003
        ECC_256_WITH_KZ = 0x0004
        TEE_TRANSIENT = 0x0005
        ECC_256_VIA_SYMMETRIC = 0x0006
        UNKNOWN = 0xffff

        @classmethod
        def _missing_(cls, value):
            return cls.UNKNOWN

    def __init__(
            self,
            key_id: UUID,
            key_type: int,
            cipher_type: int,
            key_length: int,
            key: bytes
    ):
        self.key_id = key_id
        self.key_type = self.KeyType(key_type)
        self.cipher_type = self.CipherType(cipher_type)
        self.key_length = key_length
        self.key = key

    @staticmethod
    def kid_to_uuid(kid: Union[str, bytes]) -> UUID:
        """
        Convert a Key ID from a string or bytes to a UUID object.
        At first, this may seem very simple, but some types of Key IDs
        may not be 16 bytes and some may be decimal vs. hex.
        """
        if isinstance(kid, str):
            kid = base64.b64decode(kid)
        if not kid:
            kid = b"\x00" * 16

        if kid.decode(errors="replace").isdigit():
            return UUID(int=int(kid.decode()))

        if len(kid) < 16:
            kid += b"\x00" * (16 - len(kid))

        return UUID(bytes=kid)
