"""Derive Bitcoin addresses from an extended public key (xpub/ypub/zpub).

Implements BIP32 public→public child derivation (non-hardened only, which
is all that receive/change chains need) using the pure-Python ``ecdsa``
library, plus BIP44/49/84 address encoding:

- ``xpub`` (0x0488B21E) → P2PKH  (legacy ``1…``)
- ``ypub`` (0x049D7CB2) → P2SH-P2WPKH (wrapped SegWit ``3…``)
- ``zpub`` (0x04B24746) → P2WPKH (native SegWit ``bc1…``)

No private keys are ever handled — an xpub only exposes public addresses.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ecdsa import SECP256k1, VerifyingKey
from ecdsa.ellipticcurve import Point

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Extended-key version bytes → (address kind, mainnet)
_XPUB_VERSIONS: dict[bytes, str] = {
    bytes.fromhex("0488b21e"): "p2pkh",   # xpub
    bytes.fromhex("049d7cb2"): "p2sh",    # ypub  (P2SH-P2WPKH)
    bytes.fromhex("04b24746"): "p2wpkh",  # zpub  (native segwit)
}

_P2PKH_PREFIX = b"\x00"   # mainnet pubkey hash
_P2SH_PREFIX = b"\x05"    # mainnet script hash
_BECH32_HRP = "bc"


# ── base58check ────────────────────────────────────────────────────────────

def _b58decode(s: str) -> bytes:
    num = 0
    for ch in s:
        num = num * 58 + _B58_ALPHABET.index(ch)
    full = num.to_bytes((num.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + full


def _b58decode_check(s: str) -> bytes:
    raw = _b58decode(s)
    data, checksum = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4] != checksum:
        raise ValueError("Ogiltig checksumma i xpub")
    return data


def _b58encode(data: bytes) -> str:
    num = int.from_bytes(data, "big")
    enc = ""
    while num > 0:
        num, rem = divmod(num, 58)
        enc = _B58_ALPHABET[rem] + enc
    pad = len(data) - len(data.lstrip(b"\x00"))
    return "1" * pad + enc


def _b58encode_check(data: bytes) -> str:
    checksum = hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    return _b58encode(data + checksum)


# ── bech32 (BIP173) ────────────────────────────────────────────────────────

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp: str, data: list[int]) -> list[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _bech32_encode(hrp: str, data: list[int]) -> str:
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in combined)


def _convertbits(data: bytes, frombits: int, tobits: int, pad: bool = True) -> list[int]:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def _encode_segwit(witver: int, witprog: bytes) -> str:
    return _bech32_encode(_BECH32_HRP, [witver] + _convertbits(witprog, 8, 5))


# ── hashing ────────────────────────────────────────────────────────────────

def _hash160(data: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()


# ── BIP32 ──────────────────────────────────────────────────────────────────

@dataclass
class _ExtPubKey:
    kind: str          # p2pkh | p2sh | p2wpkh
    chain_code: bytes
    point: Point       # secp256k1 public point

    def serialize_pubkey(self) -> bytes:
        """33-byte compressed SEC1 public key."""
        x = self.point.x()
        y = self.point.y()
        prefix = b"\x02" if y % 2 == 0 else b"\x03"
        return prefix + x.to_bytes(32, "big")


def _parse_xpub(xpub: str) -> _ExtPubKey:
    data = _b58decode_check(xpub.strip())
    if len(data) != 78:
        raise ValueError("Ogiltig xpub-längd")
    version = data[:4]
    kind = _XPUB_VERSIONS.get(version)
    if kind is None:
        raise ValueError(
            "Okänd extended key-typ. Använd en xpub, ypub eller zpub (mainnet)."
        )
    chain_code = data[13:45]
    key_bytes = data[45:78]
    if key_bytes[0] not in (0x02, 0x03):
        raise ValueError("xpub innehåller inte en giltig publik nyckel")
    point = VerifyingKey.from_string(
        key_bytes, curve=SECP256k1
    ).pubkey.point
    return _ExtPubKey(kind=kind, chain_code=chain_code, point=point)


def _ckd_pub(parent: _ExtPubKey, index: int) -> _ExtPubKey:
    """Non-hardened child public key derivation (BIP32)."""
    if index >= 0x80000000:
        raise ValueError("Härdad härledning är omöjlig från en xpub")
    import hmac

    data = parent.serialize_pubkey() + index.to_bytes(4, "big")
    i = hmac.new(parent.chain_code, data, hashlib.sha512).digest()
    il, ir = i[:32], i[32:]
    il_int = int.from_bytes(il, "big")
    if il_int >= SECP256k1.order:
        raise ValueError("Ogiltig härledning (il ≥ n)")
    # child point = parent point + il*G
    child_point = parent.point + (il_int * SECP256k1.generator)
    return _ExtPubKey(kind=parent.kind, chain_code=ir, point=child_point)


def _point_to_address(ext: _ExtPubKey) -> str:
    pubkey = ext.serialize_pubkey()
    h160 = _hash160(pubkey)
    if ext.kind == "p2pkh":
        return _b58encode_check(_P2PKH_PREFIX + h160)
    if ext.kind == "p2wpkh":
        return _encode_segwit(0, h160)
    if ext.kind == "p2sh":
        # P2SH-P2WPKH: redeemScript = OP_0 <20-byte-hash>; address = hash160(script)
        redeem = b"\x00\x14" + h160
        return _b58encode_check(_P2SH_PREFIX + _hash160(redeem))
    raise ValueError(f"Okänd adresstyp: {ext.kind}")


def derive_addresses(xpub: str, count: int, *, change: bool = False) -> list[str]:
    """Derive ``count`` addresses from an xpub for the receive (0) or change (1) chain.

    The xpub is expected to be the account-level key (BIP44/49/84 m/…'/…'/0'),
    so the external/internal chain is derived as m/<0|1>/<index>.
    """
    root = _parse_xpub(xpub)
    branch = _ckd_pub(root, 1 if change else 0)
    return [_point_to_address(_ckd_pub(branch, i)) for i in range(count)]


def scan_addresses(
    xpub: str,
    *,
    gap_limit: int = 20,
    is_used=None,
    max_addresses: int = 1000,
) -> list[str]:
    """Gap-limit scan both chains, returning all addresses up to the last used
    one plus a ``gap_limit`` look-ahead.

    Args:
        is_used: callable(address) -> bool. When None, no network check is done
            and exactly ``gap_limit`` addresses per chain are returned.
        max_addresses: hard cap per chain to bound runaway scans.
    """
    root = _parse_xpub(xpub)  # validate early
    del root
    found: list[str] = []
    for change in (False, True):
        branch_addrs = derive_addresses(xpub, min(gap_limit, max_addresses), change=change)
        if is_used is None:
            found.extend(branch_addrs)
            continue

        idx = 0
        consecutive_unused = 0
        last_used_idx = -1
        cache: list[str] = list(branch_addrs)
        while idx < max_addresses and consecutive_unused < gap_limit:
            if idx >= len(cache):
                cache.extend(derive_addresses(xpub, idx + gap_limit, change=change)[len(cache):])
            addr = cache[idx]
            if is_used(addr):
                last_used_idx = idx
                consecutive_unused = 0
            else:
                consecutive_unused += 1
            idx += 1
        # keep everything up to last used + gap look-ahead
        keep = min(last_used_idx + 1 + gap_limit, len(cache))
        found.extend(cache[:keep])
    return found
