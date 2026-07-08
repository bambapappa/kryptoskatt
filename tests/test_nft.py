"""Tests for NFT ledger import and its flow through GAV → K4."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.engine.gav import GavEngine
from kryptoskatt.enums import EventType
from kryptoskatt.models.base import Base
from kryptoskatt.models.transaction import ImportBatch, Transaction
from kryptoskatt.parsers.nft import NftParser, nft_symbol
from kryptoskatt.reports.k4 import K4ReportGenerator


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "nft.csv"
    p.write_text(content, encoding="utf-8")
    return p


HEADER = "date,action,collection,token_id,chain,amount_sek,fee_sek,tx_hash,notes\n"


def test_nft_symbol_is_unique_per_token():
    assert nft_symbol("Bored Apes", "1234") == "NFT:Bored Apes#1234"
    assert nft_symbol("Bored Apes", "1") != nft_symbol("Bored Apes", "2")


def test_nft_symbol_truncates_long_collection_but_keeps_token_id():
    sym = nft_symbol("X" * 200, "9999")
    assert len(sym) <= 100
    assert sym.endswith("#9999")


def test_parse_buy_and_sell(tmp_path):
    csv = HEADER + (
        "2024-03-01,BUY,Bored Apes,1234,ETHEREUM,50000,500,0xabc,minted\n"
        "2024-09-15,SELL,Bored Apes,1234,ETHEREUM,120000,1000,0xdef,\n"
    )
    result = NftParser().parse(_write(tmp_path, csv))
    assert result.errors == []
    assert len(result.transactions) == 2

    buy, sell = result.transactions
    assert buy.event_type == EventType.BUY.value
    assert buy.base_coin == "NFT:Bored Apes#1234"
    assert buy.base_amount == Decimal("1")
    assert buy.price_sek == Decimal("50000")
    assert buy.fee_coin == "SEK"
    assert buy.fee_amount == Decimal("500")

    assert sell.event_type == EventType.SELL.value
    assert sell.price_sek == Decimal("120000")


def test_unknown_action_is_an_error(tmp_path):
    csv = HEADER + "2024-03-01,STAKE,Apes,1,ETHEREUM,1,0,,\n"
    result = NftParser().parse(_write(tmp_path, csv))
    assert result.transactions == []
    assert any("unknown action" in e for e in result.errors)


def test_case_insensitive_header_and_action(tmp_path):
    csv = "Date,Action,Collection,Token_Id,Amount_SEK\n2024-03-01,buy,Punks,7,10000\n"
    result = NftParser().parse(_write(tmp_path, csv))
    assert result.errors == []
    assert result.transactions[0].base_coin == "NFT:Punks#7"


class TestNftThroughGavToK4:
    """An NFT buy+sell must produce a taxable K4 row via the standard engine."""

    @pytest.fixture
    def session(self):
        from tests.conftest import make_test_account

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        sess = Session()
        make_test_account(sess)
        yield sess
        sess.close()

    def test_gain_appears_in_k4(self, session, tmp_path):
        csv = HEADER + (
            "2024-03-01,BUY,Bored Apes,1234,ETHEREUM,50000,500,0xabc,\n"
            "2024-09-15,SELL,Bored Apes,1234,ETHEREUM,120000,1000,0xdef,\n"
        )
        result = NftParser().parse(_write(tmp_path, csv))

        batch = ImportBatch(user_id=1, platform="NFT", filename="nft.csv")
        session.add(batch)
        session.commit()
        for tc in result.transactions:
            session.add(
                Transaction(
                    user_id=1,
                    import_batch_id=batch.id,
                    source_platform=tc.source_platform,
                    timestamp_utc=tc.timestamp_utc,
                    event_type=tc.event_type,
                    base_coin=tc.base_coin,
                    base_amount=tc.base_amount,
                    fee_coin=tc.fee_coin,
                    fee_amount=tc.fee_amount,
                    price_sek=tc.price_sek,
                    raw_payload=tc.raw_payload,
                )
            )
        session.commit()

        GavEngine(session, user_id=1).calculate(2024)
        report = K4ReportGenerator(session, user_id=1).generate(2024)

        nft_rows = [r for r in report.rows if r.coin == "NFT:Bored Apes#1234"]
        assert len(nft_rows) == 1
        row = nft_rows[0]
        # proceeds = 120000 - 1000 fee; cost = 50000 + 500 fee
        assert row.proceeds_sek == Decimal("119000.00")
        assert row.cost_basis_sek == Decimal("50500.00")
        assert row.gain_loss_sek == Decimal("68500.00")
