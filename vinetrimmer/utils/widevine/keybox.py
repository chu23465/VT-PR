import struct

from crccheck.crc import Crc32Mpeg2


class Keybox:
    def __init__(self, data):
        length = len(data)
        if length not in (128, 132):
            raise ValueError(f"Invalid keybox length: {length}. Should be 128 or 132 bytes")

        if length == 128:  # QSEE style keybox
            if data[0x80:0x84] != b"LVL1":
                raise ValueError("QSEE style keybox does not end in bytes 'LVL1'")
            data = data[0:0x80]

        if data[0x78:0x7C] != b"kbox":
            raise ValueError("Invalid keybox magic")

        body_crc = Crc32Mpeg2.calc(data[:0x7C])
        body_crc_expected = struct.unpack(">L", data[0x7C:0x7C + 4])[0]
        if body_crc_expected != body_crc:
            raise ValueError(f"Keybox CRC is bad. Expected: 0x{body_crc_expected:08X}. Computed: 0x{body_crc:08X}")

        self.stable_id = data[0x00:0x20]  # aka device ID
        self.device_aes_key = data[0x20:0x30]
        self.device_id = data[0x30:0x78]  # device id sent to google, possibly flags + system_id + encrypted

        # known fields
        self.flags, self.system_id = struct.unpack(">L", self.device_id[0:8])[:2]

    def __str__(self):
        return f"{self.stable_id.decode('utf-8').strip()} ({self.system_id})"

    def __repr__(self):
        return "{name}({items})".format(
            name=self.__class__.__name__,
            items=", ".join([f"{k}={repr(v)}" for k, v in self.__dict__.items()])
        )

    @classmethod
    def load(cls, file):
        """Load Keybox from a file path."""
        with open(file, "rb", encoding="utf-8") as fd:
            return cls(fd.read())
