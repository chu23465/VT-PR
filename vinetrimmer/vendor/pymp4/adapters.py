from __future__ import annotations

from abc import ABC
from uuid import UUID

from construct import Adapter, int2byte


class ISO6392TLanguageCode(Adapter, ABC):
    def _decode(self, obj, context, path):
        return "".join([
            chr(bit + 0x60)
            for bit in (
                (obj >> 10) & 0b11111,
                (obj >> 5) & 0b11111,
                obj & 0b11111
            )
        ])

    def _encode(self, obj, context, path):
        bits = [ord(c) - 0x60 for c in obj]
        return (bits[0] << 10) | (bits[1] << 5) | bits[2]


class MaskedInteger(Adapter, ABC):
    def _decode(self, obj, context, path):
        return obj & 0x1F

    def _encode(self, obj, context, path):
        return obj & 0x1F


class UUIDBytes(Adapter, ABC):
    def _decode(self, obj, context, path):
        return UUID(bytes=obj)

    def _encode(self, obj, context, path):
        return obj.bytes
