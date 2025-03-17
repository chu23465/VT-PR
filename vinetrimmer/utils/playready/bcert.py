from __future__ import annotations
import collections.abc

from Crypto.PublicKey import ECC

from .exceptions import InvalidCertificateChain

# monkey patch for construct 2.8.8 compatibility
if not hasattr(collections, 'Sequence'):
    collections.Sequence = collections.abc.Sequence

import base64
from pathlib import Path
from typing import Union

from Crypto.Hash import SHA256
from Crypto.Signature import DSS
from construct import Bytes, Const, Int32ub, GreedyRange, Switch, Container, ListContainer
from construct import Int16ub, Array
from construct import Struct, this

from .ecc_key import ECCKey


class _BCertStructs:
    DrmBCertBasicInfo = Struct(
        "cert_id" / Bytes(16),
        "security_level" / Int32ub,
        "flags" / Int32ub,
        "cert_type" / Int32ub,
        "public_key_digest" / Bytes(32),
        "expiration_date" / Int32ub,
        "client_id" / Bytes(16)
    )

    # TODO: untested
    DrmBCertDomainInfo = Struct(
        "service_id" / Bytes(16),
        "account_id" / Bytes(16),
        "revision_timestamp" / Int32ub,
        "domain_url_length" / Int32ub,
        "domain_url" / Bytes((this.domain_url_length + 3) & 0xfffffffc)
    )

    # TODO: untested
    DrmBCertPCInfo = Struct(
        "security_version" / Int32ub
    )

    # TODO: untested
    DrmBCertDeviceInfo = Struct(
        "max_license" / Int32ub,
        "max_header" / Int32ub,
        "max_chain_depth" / Int32ub
    )

    DrmBCertFeatureInfo = Struct(
        "feature_count" / Int32ub,  # max. 32
        "features" / Array(this.feature_count, Int32ub)
    )

    DrmBCertKeyInfo = Struct(
        "key_count" / Int32ub,
        "cert_keys" / Array(this.key_count, Struct(
            "type" / Int16ub,
            "length" / Int16ub,
            "flags" / Int32ub,
            "key" / Bytes(this.length // 8),
            "usages_count" / Int32ub,
            "usages" / Array(this.usages_count, Int32ub)
        ))
    )

    DrmBCertManufacturerInfo = Struct(
        "flags" / Int32ub,
        "manufacturer_name_length" / Int32ub,
        "manufacturer_name" / Bytes((this.manufacturer_name_length + 3) & 0xfffffffc),
        "model_name_length" / Int32ub,
        "model_name" / Bytes((this.model_name_length + 3) & 0xfffffffc),
        "model_number_length" / Int32ub,
        "model_number" / Bytes((this.model_number_length + 3) & 0xfffffffc),
    )

    DrmBCertSignatureInfo = Struct(
        "signature_type" / Int16ub,
        "signature_size" / Int16ub,
        "signature" / Bytes(this.signature_size),
        "signature_key_size" / Int32ub,
        "signature_key" / Bytes(this.signature_key_size // 8)
    )

    # TODO: untested
    DrmBCertSilverlightInfo = Struct(
        "security_version" / Int32ub,
        "platform_identifier" / Int32ub
    )

    # TODO: untested
    DrmBCertMeteringInfo = Struct(
        "metering_id" / Bytes(16),
        "metering_url_length" / Int32ub,
        "metering_url" / Bytes((this.metering_url_length + 3) & 0xfffffffc)
    )

    # TODO: untested
    DrmBCertExtDataSignKeyInfo = Struct(
        "key_type" / Int16ub,
        "key_length" / Int16ub,
        "flags" / Int32ub,
        "key" / Bytes(this.length // 8)
    )

    # TODO: untested
    BCertExtDataRecord = Struct(
        "data_size" / Int32ub,
        "data" / Bytes(this.data_size)
    )

    # TODO: untested
    DrmBCertExtDataSignature = Struct(
        "signature_type" / Int16ub,
        "signature_size" / Int16ub,
        "signature" / Bytes(this.signature_size)
    )

    # TODO: untested
    BCertExtDataContainer = Struct(
        "record_count" / Int32ub,  # always 1
        "records" / Array(this.record_count, BCertExtDataRecord),
        "signature" / DrmBCertExtDataSignature
    )

    # TODO: untested
    DrmBCertServerInfo = Struct(
        "warning_days" / Int32ub
    )

    # TODO: untested
    DrmBcertSecurityVersion = Struct(
        "security_version" / Int32ub,
        "platform_identifier" / Int32ub
    )

    Attribute = Struct(
        "flags" / Int16ub,
        "tag" / Int16ub,
        "length" / Int32ub,
        "attribute" / Switch(
            lambda this_: this_.tag,
            {
                1: DrmBCertBasicInfo,
                2: DrmBCertDomainInfo,
                3: DrmBCertPCInfo,
                4: DrmBCertDeviceInfo,
                5: DrmBCertFeatureInfo,
                6: DrmBCertKeyInfo,
                7: DrmBCertManufacturerInfo,
                8: DrmBCertSignatureInfo,
                9: DrmBCertSilverlightInfo,
                10: DrmBCertMeteringInfo,
                11: DrmBCertExtDataSignKeyInfo,
                12: BCertExtDataContainer,
                13: DrmBCertExtDataSignature,
                14: Bytes(this.length - 8),
                15: DrmBCertServerInfo,
                16: DrmBcertSecurityVersion,
                17: DrmBcertSecurityVersion
            },
            default=Bytes(this.length - 8)
        )
    )

    BCert = Struct(
        "signature" / Const(b"CERT"),
        "version" / Int32ub,
        "total_length" / Int32ub,
        "certificate_length" / Int32ub,
        "attributes" / GreedyRange(Attribute)
    )

    BCertChain = Struct(
        "signature" / Const(b"CHAI"),
        "version" / Int32ub,
        "total_length" / Int32ub,
        "flags" / Int32ub,
        "certificate_count" / Int32ub,
        "certificates" / GreedyRange(BCert)
    )


class Certificate(_BCertStructs):
    """Represents a BCert"""

    def __init__(
            self,
            parsed_bcert: Container,
            bcert_obj: _BCertStructs.BCert = _BCertStructs.BCert
    ):
        self.parsed = parsed_bcert
        self._BCERT = bcert_obj

    @classmethod
    def new_leaf_cert(
            cls,
            cert_id: bytes,
            security_level: int,
            client_id: bytes,
            signing_key: ECCKey,
            encryption_key: ECCKey,
            group_key: ECCKey,
            parent: CertificateChain,
            expiry: int = 0xFFFFFFFF,
            max_license: int = 10240,
            max_header: int = 15360,
            max_chain_depth: int = 2
    ) -> Certificate:
        if not cert_id:
            raise ValueError("Certificate ID is required")
        if not client_id:
            raise ValueError("Client ID is required")

        basic_info = Container(
            cert_id=cert_id,
            security_level=security_level,
            flags=0,
            cert_type=2,
            public_key_digest=signing_key.public_sha256_digest(),
            expiration_date=expiry,
            client_id=client_id
        )
        basic_info_attribute = Container(
            flags=1,
            tag=1,
            length=len(_BCertStructs.DrmBCertBasicInfo.build(basic_info)) + 8,
            attribute=basic_info
        )

        device_info = Container(
            max_license=max_license,
            max_header=max_header,
            max_chain_depth=max_chain_depth
        )
        device_info_attribute = Container(
            flags=1,
            tag=4,
            length=len(_BCertStructs.DrmBCertDeviceInfo.build(device_info)) + 8,
            attribute=device_info
        )

        feature = Container(
            feature_count=3,
            features=ListContainer([
                4,  # SECURE_CLOCK
                9,  # REVOCATION_LIST_FEATURE
                13  # SUPPORTS_PR3_FEATURES
            ])
        )
        feature_attribute = Container(
            flags=1,
            tag=5,
            length=len(_BCertStructs.DrmBCertFeatureInfo.build(feature)) + 8,
            attribute=feature
        )

        cert_key_sign = Container(
            type=1,
            length=512,  # bits
            flags=0,
            key=signing_key.public_bytes(),
            usages_count=1,
            usages=ListContainer([
                1  # KEYUSAGE_SIGN
            ])
        )
        cert_key_encrypt = Container(
            type=1,
            length=512,  # bits
            flags=0,
            key=encryption_key.public_bytes(),
            usages_count=1,
            usages=ListContainer([
                2  # KEYUSAGE_ENCRYPT_KEY
            ])
        )
        key_info = Container(
            key_count=2,
            cert_keys=ListContainer([
                cert_key_sign,
                cert_key_encrypt
            ])
        )
        key_info_attribute = Container(
            flags=1,
            tag=6,
            length=len(_BCertStructs.DrmBCertKeyInfo.build(key_info)) + 8,
            attribute=key_info
        )

        manufacturer_info = parent.get_certificate(0).get_attribute(7)

        new_bcert_container = Container(
            signature=b"CERT",
            version=1,
            total_length=0,  # filled at a later time
            certificate_length=0,  # filled at a later time
            attributes=ListContainer([
                basic_info_attribute,
                device_info_attribute,
                feature_attribute,
                key_info_attribute,
                manufacturer_info,
            ])
        )

        payload = _BCertStructs.BCert.build(new_bcert_container)
        new_bcert_container.certificate_length = len(payload)
        new_bcert_container.total_length = len(payload) + 144  # signature length

        sign_payload = _BCertStructs.BCert.build(new_bcert_container)

        hash_obj = SHA256.new(sign_payload)
        signer = DSS.new(group_key.key, 'fips-186-3')
        signature = signer.sign(hash_obj)

        signature_info = Container(
            signature_type=1,
            signature_size=64,
            signature=signature,
            signature_key_size=512,  # bits
            signature_key=group_key.public_bytes()
        )
        signature_info_attribute = Container(
            flags=1,
            tag=8,
            length=len(_BCertStructs.DrmBCertSignatureInfo.build(signature_info)) + 8,
            attribute=signature_info
        )
        new_bcert_container.attributes.append(signature_info_attribute)

        return cls(new_bcert_container)

    @classmethod
    def loads(cls, data: Union[str, bytes]) -> Certificate:
        if isinstance(data, str):
            data = base64.b64decode(data)
        if not isinstance(data, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {data!r}")

        cert = _BCertStructs.BCert
        return cls(
            parsed_bcert=cert.parse(data),
            bcert_obj=cert
        )

    @classmethod
    def load(cls, path: Union[Path, str]) -> Certificate:
        if not isinstance(path, (Path, str)):
            raise ValueError(f"Expecting Path object or path string, got {path!r}")
        with Path(path).open(mode="rb") as f:
            return cls.loads(f.read())

    def get_attribute(self, type_: int):
        for attribute in self.parsed.attributes:
            if attribute.tag == type_:
                return attribute

    def get_security_level(self) -> int:
        basic_info_attribute = self.get_attribute(1).attribute
        if basic_info_attribute:
            return basic_info_attribute.security_level

    @staticmethod
    def _unpad(name: bytes):
        return name.rstrip(b'\x00').decode("utf-8", errors="ignore")

    def get_name(self):
        manufacturer_info = self.get_attribute(7).attribute
        if manufacturer_info:
            return f"{self._unpad(manufacturer_info.manufacturer_name)} {self._unpad(manufacturer_info.model_name)} {self._unpad(manufacturer_info.model_number)}"

    def dumps(self) -> bytes:
        return self._BCERT.build(self.parsed)

    def struct(self) -> _BCertStructs.BCert:
        return self._BCERT

    def verify_signature(self):
        sign_payload = self.dumps()[:-144]
        signature_attribute = self.get_attribute(8).attribute

        raw_signature_key = signature_attribute.signature_key
        signature_key = ECC.construct(
            curve='P-256',
            point_x=int.from_bytes(raw_signature_key[:32], 'big'),
            point_y=int.from_bytes(raw_signature_key[32:], 'big')
        )

        hash_obj = SHA256.new(sign_payload)
        verifier = DSS.new(signature_key, 'fips-186-3')

        try:
            verifier.verify(hash_obj, signature_attribute.signature)
            return True
        except ValueError:
            return False


class CertificateChain(_BCertStructs):
    """Represents a BCertChain"""

    def __init__(
            self,
            parsed_bcert_chain: Container,
            bcert_chain_obj: _BCertStructs.BCertChain = _BCertStructs.BCertChain
    ):
        self.parsed = parsed_bcert_chain
        self._BCERT_CHAIN = bcert_chain_obj

    @classmethod
    def loads(cls, data: Union[str, bytes]) -> CertificateChain:
        if isinstance(data, str):
            data = base64.b64decode(data)
        if not isinstance(data, bytes):
            raise ValueError(f"Expecting Bytes or Base64 input, got {data!r}")

        cert_chain = _BCertStructs.BCertChain
        return cls(
            parsed_bcert_chain=cert_chain.parse(data),
            bcert_chain_obj=cert_chain
        )

    @classmethod
    def load(cls, path: Union[Path, str]) -> CertificateChain:
        if not isinstance(path, (Path, str)):
            raise ValueError(f"Expecting Path object or path string, got {path!r}")
        with Path(path).open(mode="rb") as f:
            return cls.loads(f.read())

    def dumps(self) -> bytes:
        return self._BCERT_CHAIN.build(self.parsed)

    def struct(self) -> _BCertStructs.BCertChain:
        return self._BCERT_CHAIN

    def get_certificate(self, index: int) -> Certificate:
        return Certificate(self.parsed.certificates[index])

    def get_security_level(self) -> int:
        # not sure if there's a better way than this
        return self.get_certificate(0).get_security_level()

    def get_name(self) -> str:
        return self.get_certificate(0).get_name()

    def append(self, bcert: Certificate) -> None:
        self.parsed.certificate_count += 1
        self.parsed.certificates.append(bcert.parsed)
        self.parsed.total_length += len(bcert.dumps())

    def prepend(self, bcert: Certificate) -> None:
        self.parsed.certificate_count += 1
        self.parsed.certificates.insert(0, bcert.parsed)
        self.parsed.total_length += len(bcert.dumps())

    def remove(self, index: int) -> None:
        if self.parsed.certificate_count <= 0:
            raise InvalidCertificateChain("CertificateChain does not contain any Certificates")
        if index >= self.parsed.certificate_count:
            raise IndexError(f"No Certificate at index {index}, {self.parsed.certificate_count} total")

        self.parsed.certificate_count -= 1
        bcert = Certificate(self.parsed.certificates[index])
        self.parsed.total_length -= len(bcert.dumps())
        self.parsed.certificates.pop(index)

    def get(self, index: int) -> Certificate:
        if self.parsed.certificate_count <= 0:
            raise InvalidCertificateChain("CertificateChain does not contain any Certificates")
        if index >= self.parsed.certificate_count:
            raise IndexError(f"No Certificate at index {index}, {self.parsed.certificate_count} total")

        return Certificate(self.parsed.certificates[index])

    def count(self) -> int:
        return self.parsed.certificate_count
