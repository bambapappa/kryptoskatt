"""Tests for the K4 SRU export (Skatteverket electronic filing)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.reports.sru import K4SruGenerator, SruTaxpayer, _format_antal


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _uid(db):
    from tests.conftest import make_test_account
    return make_test_account(db)


def _add_disposal(db, uid, coin, amount, proceeds, cost, year=2024):
    db.add(Disposal(
        user_id=uid, tax_year=year, coin=coin,
        sell_amount=Decimal(str(amount)),
        proceeds_sek=Decimal(str(proceeds)),
        cost_basis_sek=Decimal(str(cost)),
        gain_loss_sek=Decimal(str(proceeds)) - Decimal(str(cost)),
        sell_timestamp=datetime(year, 6, 1, tzinfo=UTC),
        gav_at_disposal=Decimal("0"),
    ))


DEFAULT_TP = SruTaxpayer(
    personnummer="199001011234", namn="Test Testsson",
    postnummer="12345", postort="Stockholm",
)


class TestFormatAntal:
    def test_fractional_uses_comma(self):
        assert _format_antal(Decimal("0.06")) == "0,06"

    def test_trailing_zeros_trimmed(self):
        assert _format_antal(Decimal("1.50000000")) == "1,5"

    def test_integer_has_no_decimals(self):
        assert _format_antal(Decimal("100")) == "100"

    def test_eight_decimals_max(self):
        assert _format_antal(Decimal("0.123456789")) == "0,12345679"


class TestPersonnummer:
    def test_accepts_12_digits(self):
        assert SruTaxpayer("199001011234", "X").normalized_pnr() == "199001011234"

    def test_strips_hyphen(self):
        assert SruTaxpayer("19900101-1234", "X").normalized_pnr() == "199001011234"

    def test_rejects_10_digits(self):
        with pytest.raises(ValueError):
            SruTaxpayer("9001011234", "X").normalized_pnr()

    def test_rejects_non_numeric(self):
        with pytest.raises(ValueError):
            SruTaxpayer("19900101ABCD", "X").normalized_pnr()


class TestGenerate:
    def test_no_disposals_raises(self, db_session):
        uid = _uid(db_session)
        db_session.commit()
        with pytest.raises(ValueError, match="Inga avyttringar"):
            K4SruGenerator(db_session, uid).generate(2024, DEFAULT_TP)

    def test_info_sru_structure(self, db_session):
        uid = _uid(db_session)
        _add_disposal(db_session, uid, "BTC", "-0.1", "30000", "20000")
        db_session.commit()
        export = K4SruGenerator(db_session, uid).generate(2024, DEFAULT_TP)
        info = export.info_sru
        assert "#DATABESKRIVNING_START" in info
        assert "#PRODUKT SRU" in info
        assert "#FILNAMN BLANKETTER.SRU" in info
        assert "#ORGNR 199001011234" in info
        assert "#NAMN Test Testsson" in info
        assert "#POSTNR 12345" in info
        assert "#MEDIELEV_SLUT" in info

    def test_section_d_field_codes_and_values(self, db_session):
        uid = _uid(db_session)
        # BTC gain, ETH loss
        _add_disposal(db_session, uid, "BTC", "-0.06", "30000.40", "20000.10")
        _add_disposal(db_session, uid, "BTC", "-0.04", "22000", "18000")
        _add_disposal(db_session, uid, "ETH", "-1.5", "15000", "20000")
        db_session.commit()

        blank = K4SruGenerator(db_session, uid).generate(
            2024, DEFAULT_TP, created_at=datetime(2025, 5, 2, 10, 30, 0, tzinfo=UTC)
        ).blanketter_sru
        lines = blank.split("\r\n")

        # Blankett header
        assert "#BLANKETT K4-2024P4" in lines
        assert "#IDENTITET 199001011234 20250502 103000" in lines
        # BTC (sorted first): row 341x, antal 0.10 -> "0,1"
        assert "#UPPGIFT 3410 0,1" in lines
        assert "#UPPGIFT 3411 BTC" in lines
        assert "#UPPGIFT 3412 52000" in lines   # 30000.40+22000 rounded
        assert "#UPPGIFT 3413 38000" in lines   # 20000.10+18000 rounded
        assert "#UPPGIFT 3414 14000" in lines   # gain
        assert "#UPPGIFT 3415 0" in lines       # no loss
        # ETH (sorted second): row 342x, loss
        assert "#UPPGIFT 3420 1,5" in lines
        assert "#UPPGIFT 3421 ETH" in lines
        assert "#UPPGIFT 3424 0" in lines       # no gain
        assert "#UPPGIFT 3425 5000" in lines    # loss
        # Section D summary
        assert "#UPPGIFT 3500 67000" in lines   # 52000+15000
        assert "#UPPGIFT 3501 58000" in lines   # 38000+20000
        assert "#UPPGIFT 3503 14000" in lines
        assert "#UPPGIFT 3504 5000" in lines
        assert "#UPPGIFT 7014 1" in lines
        assert "#BLANKETTSLUT" in lines
        assert lines[-2] == "#FIL_SLUT" or "#FIL_SLUT" in lines

    def test_pagination_over_seven_coins(self, db_session):
        uid = _uid(db_session)
        for i in range(9):  # 9 coins -> 2 pages (7 + 2)
            _add_disposal(db_session, uid, f"COIN{i:02d}", "-1", "1000", "500")
        db_session.commit()

        blank = K4SruGenerator(db_session, uid).generate(2024, DEFAULT_TP).blanketter_sru
        # Two blankett blocks
        assert blank.count("#BLANKETT K4-2024P4") == 2
        assert blank.count("#BLANKETTSLUT") == 2
        assert "#UPPGIFT 7014 1" in blank
        assert "#UPPGIFT 7014 2" in blank
        # Page 2 restarts row numbering at 341x
        page2 = blank.split("#BLANKETTSLUT")[1]
        assert "#UPPGIFT 3410 " in page2
        assert "#UPPGIFT 3420 " in page2
        # Only one #FIL_SLUT at the very end
        assert blank.count("#FIL_SLUT") == 1

    def test_isolation_between_users(self, db_session):
        uid1 = _uid(db_session)
        _add_disposal(db_session, uid1, "BTC", "-1", "1000", "500")
        db_session.commit()
        # A different user has no disposals
        from kryptoskatt.services.auth import AuthService
        acc2, _ = AuthService(db_session).create_account()
        with pytest.raises(ValueError, match="Inga avyttringar"):
            K4SruGenerator(db_session, acc2.id).generate(2024, DEFAULT_TP)

    def test_latin1_encodable(self, db_session):
        uid = _uid(db_session)
        _add_disposal(db_session, uid, "BTC", "-1", "1000", "500")
        db_session.commit()
        tp = SruTaxpayer(personnummer="199001011234", namn="Åsa Öberg",
                         postort="Malmö", adress="Storgatan 3")
        export = K4SruGenerator(db_session, uid).generate(2024, tp)
        # Must round-trip through ISO-8859-1 (Skatteverket's required encoding)
        export.info_sru.encode("iso-8859-1")
        export.blanketter_sru.encode("iso-8859-1")


class TestSruWebFlow:
    """End-to-end web download and the CodeQL open-redirect / privacy fix."""

    @pytest.fixture
    def client_and_db(self):
        from fastapi.testclient import TestClient

        from kryptoskatt.db import get_db
        from kryptoskatt.services.auth import AuthService
        from kryptoskatt.web import auth as web_auth
        from kryptoskatt.web.app import app

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        acc, token = AuthService(db).create_account()
        _add_disposal(db, acc.id, "BTC", "-0.1", "30000", "20000")
        db.commit()

        def ov():
            yield db

        app.dependency_overrides[get_db] = ov
        app.dependency_overrides[web_auth._get_db_session] = ov
        client = TestClient(
            app, cookies={"kryptoskatt_session": token},
            follow_redirects=False, headers={"origin": "http://testserver"},
        )
        try:
            yield client
        finally:
            app.dependency_overrides.clear()

    def test_success_returns_zip_with_both_files(self, client_and_db):
        import io
        import zipfile

        resp = client_and_db.post(
            "/year/2024/download/sru",
            data={"personnummer": "199001011234", "namn": "Test Testsson"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert set(zf.namelist()) == {"INFO.SRU", "BLANKETTER.SRU"}

    def test_bad_personnummer_does_not_leak_into_redirect(self, client_and_db):
        """Regression for CodeQL open-redirect: only a fixed code is reflected."""
        resp = client_and_db.post(
            "/year/2024/download/sru",
            data={"personnummer": "123-SECRET", "namn": "Leaky Name"},
        )
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert loc == "/year/2024?sru_error=pnr"
        assert "SECRET" not in loc
        assert "Leaky" not in loc
