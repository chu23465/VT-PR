import base64
from typing import Union, List
from uuid import UUID

from construct import Struct, Int32ul, Int16ul, Array, this, Bytes, Switch, Int32ub, Const, Container, ConstructError

from pyplayready.exceptions import InvalidPssh
from pyplayready.system.wrmheader import WRMHeader


class _PlayreadyPSSHStructs:
    PSSHBox = Struct(
        "length" / Int32ub,
        "pssh" / Const(b"pssh"),
        "fullbox" / Int32ub,
        "system_id" / Bytes(16),
        "data_length" / Int32ub,
        "data" / Bytes(this.data_length)
    )

    PlayreadyObject = Struct(
        "type" / Int16ul,
        "length" / Int16ul,
        "data" / Switch(
            this.type,
            {
                1: Bytes(this.length)
            },
            default=Bytes(this.length)
        )
    )

    PlayreadyHeader = Struct(
        "length" / Int32ul,
        "record_count" / Int16ul,
        "records" / Array(this.record_count, PlayreadyObject)
    )


class PSSH(_PlayreadyPSSHStructs):
    """Represents a PlayReady PSSH"""

    SYSTEM_ID = UUID(hex="9a04f07998404286ab92e65be0885f95")

    def __init__(self, data: Union[str, bytes]):
        """Load a PSSH Box, PlayReady Header or PlayReady Object"""

        if not data:
            raise InvalidPssh("Data must not be empty")

        if isinstance(data, str):
            try:
                data = base64.b64decode(data)
            except Exception as e:
                raise InvalidPssh(f"Could not decode data as Base64, {e}")

        self.wrm_headers: List[WRMHeader]
        try:
            # PSSH Box -> PlayReady Header
            box = self.PSSHBox.parse(data)
            prh = self.PlayreadyHeader.parse(box.data)
            self.wrm_headers = self._read_playready_objects(prh)
        except ConstructError:
            if int.from_bytes(data[:2], byteorder="little") > 3:
                try:
                    # PlayReady Header
                    prh = self.PlayreadyHeader.parse(data)
                    self.wrm_headers = self._read_playready_objects(prh)
                except ConstructError:
                    raise InvalidPssh("Could not parse data as a PSSH Box nor a PlayReady Header")
            else:
                try:
                    # PlayReady Object
                    pro = self.PlayreadyObject.parse(data)
                    self.wrm_headers = [WRMHeader(pro.data)]
                except ConstructError:
                    raise InvalidPssh("Could not parse data as a PSSH Box nor a PlayReady Object")

    @staticmethod
    def _read_playready_objects(header: Container) -> List[WRMHeader]:
        return list(map(
            lambda pro: WRMHeader(pro.data),
            filter(
                lambda pro: pro.type == 1,
                header.records
            )
        ))

    def get_wrm_headers(self) -> List[str]:
        """
        Return a list of all WRM Headers in the PSSH as plaintext strings
        """
        return list(map(
            lambda wrm_header: wrm_header.dumps(),
            self.wrm_headers
        ))
