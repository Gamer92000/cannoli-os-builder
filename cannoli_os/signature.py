from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cannoli_os.fit import Fit

IMAGE = "/images/kernel-1"
PSS_TRAILER = 0xBC
SIG = "/configurations/conf-1/signature-1"


def mgf1(seed: bytes, length: int) -> bytes:
    return b"".join(
        hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
        for i in range((length + 31) // 32)
    )[:length]


def verify_pss(fit: Fit, key: Fit) -> bool:
    signature = fit.prop(SIG, "value")
    modulus = int.from_bytes(key.prop("/signature/key-fit", "rsa,modulus"), "big")
    exponent = int.from_bytes(key.prop("/signature/key-fit", "rsa,exponent"), "big")
    length = (modulus.bit_length() + 7) // 8
    encoded = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(
        length, "big"
    )
    if encoded[-1] != PSS_TRAILER:
        return False
    h = encoded[-33:-1]
    masked = encoded[:-33]
    db = bytearray(a ^ b for a, b in zip(masked, mgf1(h, len(masked))))
    db[0] &= 0x7F
    try:
        delimiter = db.index(1)
    except ValueError:
        return False
    if any(db[:delimiter]):
        return False
    digest = hashlib.sha256(fit.signed_stream(SIG)).digest()
    return hashlib.sha256(b"\0" * 8 + digest + db[delimiter + 1 :]).digest() == h
