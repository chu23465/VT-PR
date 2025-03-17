from __future__ import annotations

import base64
from pathlib import Path
from typing import Union

from construct import Const, GreedyRange, Struct, Int32ub, Bytes, Int16ub, this, Switch, LazyBound, Array, Container


class _XMRLicenseStructs:
    PlayEnablerType = Struct(
        "player_enabler_type" / Bytes(16)
    )

    DomainRestrictionObject = Struct(
        "account_id" / Bytes(16),
        "revision" / Int32ub
    )

    IssueDateObject = Struct(
        "issue_date" / Int32ub
    )

    RevInfoVersionObject = Struct(
        "sequence" / Int32ub
    )

    SecurityLevelObject = Struct(
        "minimum_security_level" / Int16ub
    )

    EmbeddedLicenseSettingsObject = Struct(
        "indicator" / Int16ub
    )

    ECCKeyObject = Struct(
        "curve_type" / Int16ub,
        "key_length" / Int16ub,
        "key" / Bytes(this.key_length)
    )

    SignatureObject = Struct(
        "signature_type" / Int16ub,
        "signature_data_length" / Int16ub,
        "signature_data" / Bytes(this.signature_data_length)
    )

    ContentKeyObject = Struct(
        "key_id" / Bytes(16),
        "key_type" / Int16ub,
        "cipher_type" / Int16ub,
        "key_length" / Int16ub,
        "encrypted_key" / Bytes(this.key_length)
    )

    RightsSettingsObject = Struct(
        "rights" / Int16ub
    )

    OutputProtectionLevelRestrictionObject = Struct(
        "minimum_compressed_digital_video_opl" / Int16ub,
        "minimum_uncompressed_digital_video_opl" / Int16ub,
        "minimum_analog_video_opl" / Int16ub,
        "minimum_digital_compressed_audio_opl" / Int16ub,
        "minimum_digital_uncompressed_audio_opl" / Int16ub,
    )

    ExpirationRestrictionObject = Struct(
        "begin_date" / Int32ub,
        "end_date" / Int32ub
    )

    RemovalDateObject = Struct(
        "removal_date" / Int32ub
    )

    UplinkKIDObject = Struct(
        "uplink_kid" / Bytes(16),
        "chained_checksum_type" / Int16ub,
        "chained_checksum_length" / Int16ub,
        "chained_checksum" / Bytes(this.chained_checksum_length)
    )

    AnalogVideoOutputConfigurationRestriction = Struct(
        "video_output_protection_id" / Bytes(16),
        "binary_configuration_data" / Bytes(this._.length - 24)
    )

    DigitalVideoOutputRestrictionObject = Struct(
        "video_output_protection_id" / Bytes(16),
        "binary_configuration_data" / Bytes(this._.length - 24)
    )

    DigitalAudioOutputRestrictionObject = Struct(
        "audio_output_protection_id" / Bytes(16),
        "binary_configuration_data" / Bytes(this._.length - 24)
    )

    PolicyMetadataObject = Struct(
        "metadata_type" / Bytes(16),
        "policy_data" / Bytes(this._.length)
    )

    SecureStopRestrictionObject = Struct(
        "metering_id" / Bytes(16)
    )

    MeteringRestrictionObject = Struct(
        "metering_id" / Bytes(16)
    )

    ExpirationAfterFirstPlayRestrictionObject = Struct(
        "seconds" / Int32ub
    )

    GracePeriodObject = Struct(
        "grace_period" / Int32ub
    )

    SourceIdObject = Struct(
        "source_id" / Int32ub
    )

    AuxiliaryKey = Struct(
        "location" / Int32ub,
        "key" / Bytes(16)
    )

    AuxiliaryKeysObject = Struct(
        "count" / Int16ub,
        "auxiliary_keys" / Array(this.count, AuxiliaryKey)
    )

    UplinkKeyObject3 = Struct(
        "uplink_key_id" / Bytes(16),
        "chained_length" / Int16ub,
        "checksum" / Bytes(this.chained_length),
        "count" / Int16ub,
        "entries" / Array(this.count, Int32ub)
    )

    CopyEnablerObject = Struct(
        "copy_enabler_type" / Bytes(16)
    )

    CopyCountRestrictionObject = Struct(
        "count" / Int32ub
    )

    MoveObject = Struct(
        "minimum_move_protection_level" / Int32ub
    )

    XmrObject = Struct(
        "flags" / Int16ub,
        "type" / Int16ub,
        "length" / Int32ub,
        "data" / Switch(
            lambda ctx: ctx.type,
            {
                0x0005: OutputProtectionLevelRestrictionObject,
                0x0008: AnalogVideoOutputConfigurationRestriction,
                0x000a: ContentKeyObject,
                0x000b: SignatureObject,
                0x000d: RightsSettingsObject,
                0x0012: ExpirationRestrictionObject,
                0x0013: IssueDateObject,
                0x0016: MeteringRestrictionObject,
                0x001a: GracePeriodObject,
                0x0022: SourceIdObject,
                0x002a: ECCKeyObject,
                0x002c: PolicyMetadataObject,
                0x0029: DomainRestrictionObject,
                0x0030: ExpirationAfterFirstPlayRestrictionObject,
                0x0031: DigitalAudioOutputRestrictionObject,
                0x0032: RevInfoVersionObject,
                0x0033: EmbeddedLicenseSettingsObject,
                0x0034: SecurityLevelObject,
                0x0037: MoveObject,
                0x0039: PlayEnablerType,
                0x003a: CopyEnablerObject,
                0x003b: UplinkKIDObject,
                0x003d: CopyCountRestrictionObject,
                0x0050: RemovalDateObject,
                0x0051: AuxiliaryKeysObject,
                0x0052: UplinkKeyObject3,
                0x005a: SecureStopRestrictionObject,
                0x0059: DigitalVideoOutputRestrictionObject
            },
            default=LazyBound(lambda ctx: _XMRLicenseStructs.XmrObject)
        )
    )

    XmrLicense = Struct(
        "signature" / Const(b"XMR\x00"),
        "xmr_version" / Int32ub,
        "rights_id" / Bytes(16),
        "containers" / GreedyRange(XmrObject)
    )


class XMRLicense(_XMRLicenseStructs):
    """Represents an XMRLicense"""

    def __init__(
            self,
            parsed_license: Container,
            license_obj: _XMRLicenseStructs.XmrLicense = _XMRLicenseStructs.XmrLicense
    ):
        self.parsed = parsed_license
        self._license_obj = license_obj

    @classmethod
    def loads(cls, data: Union[str, bytes]) -> XMRLicense:
        if isinstance(data, str):
            data = base64.b64decode(data)
        if not isinstance(data, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {data!r}")

        licence = _XMRLicenseStructs.XmrLicense
        return cls(
            parsed_license=licence.parse(data),
            license_obj=licence
        )

    @classmethod
    def load(cls, path: Union[Path, str]) -> XMRLicense:
        if not isinstance(path, (Path, str)):
            raise ValueError(f"Expecting Path object or path string, got {path!r}")
        with Path(path).open(mode="rb") as f:
            return cls.loads(f.read())

    def dumps(self) -> bytes:
        return self._license_obj.build(self.parsed)

    def struct(self) -> _XMRLicenseStructs.XmrLicense:
        return self._license_obj

    def _locate(self, container: Container):
        if container.flags == 2 or container.flags == 3:
            return self._locate(container.data)
        else:
            return container

    def get_object(self, type_: int):
        for obj in self.parsed.containers:
            container = self._locate(obj)
            if container.type == type_:
                yield container.data

    def get_content_keys(self):
        for content_key in self.get_object(10):
            yield content_key
