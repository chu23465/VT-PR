from __future__ import annotations

import base64
import math
import time
from typing import List, Union
from uuid import UUID
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Random import get_random_bytes
from Crypto.Signature import DSS
from Crypto.Util.Padding import pad
from ecpy.curves import Point, Curve

from .bcert import CertificateChain
from .ecc_key import ECCKey
from .key import Key
from .xml_key import XmlKey
from .elgamal import ElGamal
from .xmrlicense import XMRLicense

from .exceptions import (InvalidSession, TooManySessions, InvalidLicense)
from .session import Session


class Cdm:

    MAX_NUM_OF_SESSIONS = 16

    def __init__(
            self,
            security_level: int,
            certificate_chain: Union[CertificateChain, None],
            encryption_key: Union[ECCKey, None],
            signing_key: Union[ECCKey, None],
            client_version: str = "10.0.16384.10011",
            protocol_version: int = 1
    ):
        self.security_level = security_level
        self.certificate_chain = certificate_chain
        self.encryption_key = encryption_key
        self.signing_key = signing_key
        self.client_version = client_version
        self.protocol_version = protocol_version

        self.curve = Curve.get_curve("secp256r1")
        self.elgamal = ElGamal(self.curve)

        self._wmrm_key = Point(
            x=0xc8b6af16ee941aadaa5389b4af2c10e356be42af175ef3face93254e7b0b3d9b,
            y=0x982b27b5cb2341326e56aa857dbfd5c634ce2cf9ea74fca8f2af5957efeea562,
            curve=self.curve
        )

        self.__sessions: dict[bytes, Session] = {}

    @classmethod
    def from_device(cls, device) -> Cdm:
        """Initialize a Playready CDM from a Playready Device (.prd) file"""
        return cls(
            security_level=device.security_level,
            certificate_chain=device.group_certificate,
            encryption_key=device.encryption_key,
            signing_key=device.signing_key
        )

    def open(self) -> bytes:
        """
        Open a Playready Content Decryption Module (CDM) session.

        Raises:
            TooManySessions: If the session cannot be opened as limit has been reached.
        """
        if len(self.__sessions) > self.MAX_NUM_OF_SESSIONS:
            raise TooManySessions(f"Too many Sessions open ({self.MAX_NUM_OF_SESSIONS}).")

        session = Session(len(self.__sessions) + 1)
        self.__sessions[session.id] = session
        session.xml_key = XmlKey()

        return session.id

    def close(self, session_id: bytes) -> None:
        """
        Close a Playready Content Decryption Module (CDM) session.

        Parameters:
            session_id: Session identifier.

        Raises:
            InvalidSession: If the Session identifier is invalid.
        """
        session = self.__sessions.get(session_id)
        if not session:
            raise InvalidSession(f"Session identifier {session_id!r} is invalid.")
        del self.__sessions[session_id]

    def _get_key_data(self, session: Session) -> bytes:
        point1, point2 = self.elgamal.encrypt(
            message_point=session.xml_key.get_point(self.elgamal.curve),
            public_key=self._wmrm_key
        )
        return self.elgamal.to_bytes(point1.x) + self.elgamal.to_bytes(point1.y) + self.elgamal.to_bytes(point2.x) + self.elgamal.to_bytes(point2.y)

    def _get_cipher_data(self, session: Session) -> bytes:
        b64_chain = base64.b64encode(self.certificate_chain.dumps()).decode()
        body = f"<Data><CertificateChains><CertificateChain>{b64_chain}</CertificateChain></CertificateChains></Data>"

        cipher = AES.new(
            key=session.xml_key.aes_key,
            mode=AES.MODE_CBC,
            iv=session.xml_key.aes_iv
        )

        ciphertext = cipher.encrypt(pad(
            body.encode(),
            AES.block_size
        ))

        return session.xml_key.aes_iv + ciphertext

    def _build_digest_content(
            self,
            wrm_header: str,
            nonce: str,
            wmrm_cipher: str,
            cert_cipher: str
    ) -> str:
        return (
            '<LA xmlns="http://schemas.microsoft.com/DRM/2007/03/protocols" Id="SignedData" xml:space="preserve">'
                f'<Version>{self.protocol_version}</Version>'
                f'<ContentHeader>{wrm_header}</ContentHeader>'
                '<CLIENTINFO>'
                    f'<CLIENTVERSION>{self.client_version}</CLIENTVERSION>'
                '</CLIENTINFO>'
                f'<LicenseNonce>{nonce}</LicenseNonce>'
                f'<ClientTime>{math.floor(time.time())}</ClientTime>'
                '<EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#" Type="http://www.w3.org/2001/04/xmlenc#Element">'
                    '<EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"></EncryptionMethod>'
                    '<KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">'
                        '<EncryptedKey xmlns="http://www.w3.org/2001/04/xmlenc#">'
                            '<EncryptionMethod Algorithm="http://schemas.microsoft.com/DRM/2007/03/protocols#ecc256"></EncryptionMethod>'
                            '<KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">'
                                '<KeyName>WMRMServer</KeyName>'
                            '</KeyInfo>'
                            '<CipherData>'
                                f'<CipherValue>{wmrm_cipher}</CipherValue>'
                            '</CipherData>'
                        '</EncryptedKey>'
                    '</KeyInfo>'
                    '<CipherData>'
                        f'<CipherValue>{cert_cipher}</CipherValue>'
                    '</CipherData>'
                '</EncryptedData>'
            '</LA>'
        )

    @staticmethod
    def _build_signed_info(digest_value: str) -> str:
        return (
            '<SignedInfo xmlns="http://www.w3.org/2000/09/xmldsig#">'
                '<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"></CanonicalizationMethod>'
                '<SignatureMethod Algorithm="http://schemas.microsoft.com/DRM/2007/03/protocols#ecdsa-sha256"></SignatureMethod>'
                '<Reference URI="#SignedData">'
                    '<DigestMethod Algorithm="http://schemas.microsoft.com/DRM/2007/03/protocols#sha256"></DigestMethod>'
                    f'<DigestValue>{digest_value}</DigestValue>'
                '</Reference>'
            '</SignedInfo>'
        )

    def get_license_challenge(self, session_id: bytes, wrm_header: str) -> str:
        session = self.__sessions.get(session_id)
        if not session:
            raise InvalidSession(f"Session identifier {session_id!r} is invalid.")

        session.signing_key = self.signing_key
        session.encryption_key = self.encryption_key

        la_content = self._build_digest_content(
            wrm_header=wrm_header,
            nonce=base64.b64encode(get_random_bytes(16)).decode(),
            wmrm_cipher=base64.b64encode(self._get_key_data(session)).decode(),
            cert_cipher=base64.b64encode(self._get_cipher_data(session)).decode()
        )

        la_hash_obj = SHA256.new()
        la_hash_obj.update(la_content.encode())
        la_hash = la_hash_obj.digest()

        signed_info = self._build_signed_info(base64.b64encode(la_hash).decode())
        signed_info_digest = SHA256.new(signed_info.encode())

        signer = DSS.new(session.signing_key.key, 'fips-186-3')
        signature = signer.sign(signed_info_digest)

        # haven't found a better way to do this. xmltodict.unparse doesn't work
        main_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                '<soap:Body>'
                    '<AcquireLicense xmlns="http://schemas.microsoft.com/DRM/2007/03/protocols">'
                        '<challenge>'
                            '<Challenge xmlns="http://schemas.microsoft.com/DRM/2007/03/protocols/messages">'
                                + la_content +
                                '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">'
                                    + signed_info +
                                    f'<SignatureValue>{base64.b64encode(signature).decode()}</SignatureValue>'
                                    '<KeyInfo xmlns="http://www.w3.org/2000/09/xmldsig#">'
                                        '<KeyValue>'
                                            '<ECCKeyValue>'
                                                f'<PublicKey>{base64.b64encode(session.signing_key.public_bytes()).decode()}</PublicKey>'
                                            '</ECCKeyValue>'
                                        '</KeyValue>'
                                    '</KeyInfo>'
                                '</Signature>'
                            '</Challenge>'
                        '</challenge>'
                    '</AcquireLicense>'
                '</soap:Body>'
            '</soap:Envelope>'
        )

        return main_body

    def _decrypt_ecc256_key(self, session: Session, encrypted_key: bytes) -> bytes:
        point1 = Point(
            x=int.from_bytes(encrypted_key[:32], 'big'),
            y=int.from_bytes(encrypted_key[32:64], 'big'),
            curve=self.curve
        )
        point2 = Point(
            x=int.from_bytes(encrypted_key[64:96], 'big'),
            y=int.from_bytes(encrypted_key[96:128], 'big'),
            curve=self.curve
        )

        decrypted = self.elgamal.decrypt((point1, point2), int(session.encryption_key.key.d))
        return self.elgamal.to_bytes(decrypted.x)[16:32]

    @staticmethod
    def _verify_ecc_key(session: Session, licence: XMRLicense) -> bool:
        ecc_keys = list(licence.get_object(42))
        if not ecc_keys:
            raise InvalidLicense("No ECC public key in license")

        return ecc_keys[0].key == session.encryption_key.public_bytes()

    def parse_license(self, session_id: bytes, licence: str) -> None:
        session = self.__sessions.get(session_id)
        if not session:
            raise InvalidSession(f"Session identifier {session_id!r} is invalid.")

        if not session.encryption_key or not session.signing_key:
            raise InvalidSession("Cannot parse a license message without first making a license request")

        try:
            root = ET.fromstring(licence)
            license_elements = root.findall(".//{http://schemas.microsoft.com/DRM/2007/03/protocols}License")
            for license_element in license_elements:
                parsed_licence = XMRLicense.loads(license_element.text)

                if not self._verify_ecc_key(session, parsed_licence):
                    raise InvalidLicense("Public encryption key does not match")

                for key in parsed_licence.get_content_keys():
                    if Key.CipherType(key.cipher_type) == Key.CipherType.ECC_256:
                        session.keys.append(Key(
                            key_id=UUID(bytes_le=key.key_id),
                            key_type=key.key_type,
                            cipher_type=key.cipher_type,
                            key_length=key.key_length,
                            key=self._decrypt_ecc256_key(session, key.encrypted_key)
                        ))
        except InvalidLicense as e:
            raise InvalidLicense(e)
        except Exception as e:
            raise Exception(f"Unable to parse license, {e}")

    def get_keys(self, session_id: bytes) -> List[Key]:
        session = self.__sessions.get(session_id)
        if not session:
            raise InvalidSession(f"Session identifier {session_id!r} is invalid.")

        return session.keys
