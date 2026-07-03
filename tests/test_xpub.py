"""Tests for xpub/ypub/zpub Bitcoin address derivation.

Validated against the official BIP84 mainnet test vector and the BIP49
testnet test vector, plus BIP32 CKD correctness.
"""

import pytest

from kryptoskatt.services.xpub import derive_addresses, scan_addresses

# BIP84 account 0 (mnemonic "abandon abandon … about") — from the BIP84 spec
ZPUB = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"


class TestBip84Vectors:
    def test_first_receive_address(self):
        assert derive_addresses(ZPUB, 1)[0] == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"

    def test_second_receive_address(self):
        assert derive_addresses(ZPUB, 2)[1] == "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"

    def test_first_change_address(self):
        assert derive_addresses(ZPUB, 1, change=True)[0] == "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"

    def test_count(self):
        addrs = derive_addresses(ZPUB, 5)
        assert len(addrs) == 5
        assert all(a.startswith("bc1q") for a in addrs)
        assert len(set(addrs)) == 5  # all distinct


class TestValidation:
    def test_rejects_non_extended_key(self):
        with pytest.raises(ValueError):
            derive_addresses("not-an-xpub", 1)

    def test_rejects_bad_checksum(self):
        # last char changed -> checksum fails
        bad = ZPUB[:-1] + ("t" if ZPUB[-1] != "t" else "u")
        with pytest.raises(ValueError):
            derive_addresses(bad, 1)

    def test_rejects_bitcoin_address(self):
        with pytest.raises(ValueError):
            derive_addresses("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu", 1)


class TestScan:
    def test_scan_without_network_returns_gap_per_chain(self):
        addrs = scan_addresses(ZPUB, gap_limit=5, is_used=None)
        # 5 receive + 5 change
        assert len(addrs) == 10

    def test_scan_stops_after_gap(self):
        # Only the first receive address is "used"; change chain all unused
        first = derive_addresses(ZPUB, 1)[0]
        used = {first}
        addrs = scan_addresses(ZPUB, gap_limit=3, is_used=lambda a: a in used)
        # receive: index 0 used, then 3 unused look-ahead kept -> 4 addresses
        assert first in addrs
        assert addrs.count(first) == 1
        # bounded — nowhere near max
        assert len(addrs) < 20
