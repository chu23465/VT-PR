from typing import Union, Tuple

from Crypto.Hash import SHA256
from Crypto.Hash.SHA256 import SHA256Hash
from Crypto.PublicKey.ECC import EccKey
from Crypto.Signature import DSS
from ecpy.curves import Point, Curve

from pyplayready.crypto.elgamal import ElGamal
from pyplayready.crypto.ecc_key import ECCKey


class Crypto:
    def __init__(self, curve: str = "secp256r1"):
        self.curve = Curve.get_curve(curve)
        self.elgamal = ElGamal(self.curve)

    def ecc256_encrypt(self, public_key: Union[ECCKey, Point], plaintext: Union[Point, bytes]) -> bytes:
        if isinstance(public_key, ECCKey):
            public_key = public_key.get_point(self.curve)
        if not isinstance(public_key, Point):
            raise ValueError(f"Expecting ECCKey or Point input, got {public_key!r}")

        if isinstance(plaintext, bytes):
            plaintext = Point(
                x=int.from_bytes(plaintext[:32], 'big'),
                y=int.from_bytes(plaintext[32:64], 'big'),
                curve=self.curve
            )
        if not isinstance(plaintext, Point):
            raise ValueError(f"Expecting Point or Bytes input, got {plaintext!r}")

        point1, point2 = self.elgamal.encrypt(
            message_point=plaintext,
            public_key=public_key
        )
        return b''.join([
            self.elgamal.to_bytes(point1.x),
            self.elgamal.to_bytes(point1.y),
            self.elgamal.to_bytes(point2.x),
            self.elgamal.to_bytes(point2.y)
        ])

    def ecc256_decrypt(self, private_key: ECCKey, ciphertext: Union[Tuple[Point, Point], bytes]) -> bytes:
        if isinstance(ciphertext, bytes):
            ciphertext = (
                Point(
                    x=int.from_bytes(ciphertext[:32], 'big'),
                    y=int.from_bytes(ciphertext[32:64], 'big'),
                    curve=self.curve
                ),
                Point(
                    x=int.from_bytes(ciphertext[64:96], 'big'),
                    y=int.from_bytes(ciphertext[96:128], 'big'),
                    curve=self.curve
                )
            )
        if not isinstance(ciphertext, Tuple):
            raise ValueError(f"Expecting Tuple[Point, Point] or Bytes input, got {ciphertext!r}")

        decrypted = self.elgamal.decrypt(ciphertext, int(private_key.key.d))
        return self.elgamal.to_bytes(decrypted.x)

    @staticmethod
    def ecc256_sign(private_key: Union[ECCKey, EccKey], data: Union[SHA256Hash, bytes]) -> bytes:
        if isinstance(private_key, ECCKey):
            private_key = private_key.key
        if not isinstance(private_key, EccKey):
            raise ValueError(f"Expecting ECCKey or EccKey input, got {private_key!r}")

        if isinstance(data, bytes):
            data = SHA256.new(data)
        if not isinstance(data, SHA256Hash):
            raise ValueError(f"Expecting SHA256Hash or Bytes input, got {data!r}")

        signer = DSS.new(private_key, 'fips-186-3')
        return signer.sign(data)

    @staticmethod
    def ecc256_verify(public_key: Union[ECCKey, EccKey], data: Union[SHA256Hash, bytes], signature: bytes) -> bool:
        if isinstance(public_key, ECCKey):
            public_key = public_key.key
        if not isinstance(public_key, EccKey):
            raise ValueError(f"Expecting ECCKey or EccKey input, got {public_key!r}")

        if isinstance(data, bytes):
            data = SHA256.new(data)
        if not isinstance(data, SHA256Hash):
            raise ValueError(f"Expecting SHA256Hash or Bytes input, got {data!r}")

        verifier = DSS.new(public_key, 'fips-186-3')
        try:
            verifier.verify(data, signature)
            return True
        except ValueError:
            return False
