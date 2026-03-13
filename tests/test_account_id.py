"""Tests for account ID generation."""

import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.services.account_id import generate_account_id_unique

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Fresh in-memory DB for each test."""
    from tests.conftest import make_test_account

    Base.metadata.create_all(engine)
    session = TestingSession()
    make_test_account(session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_generate_format(db_session):
    account_id = generate_account_id_unique(db_session)

    assert re.match(r"^[a-z]+-[a-z]+-[a-z]+-\d{4}$", account_id)


def test_generate_unique_ids(db_session):
    ids = [generate_account_id_unique(db_session) for _ in range(5)]

    assert len(set(ids)) == 5


def test_generate_words_from_wordlist(db_session):
    account_id = generate_account_id_unique(db_session)

    parts = account_id.rsplit("-", 1)
    word_part = parts[0]
    words = word_part.split("-")

    assert len(words) == 3
    for word in words:
        assert word.isalpha(), f"Expected all alpha, got: {word!r}"
        assert word.islower(), f"Expected lowercase, got: {word!r}"
        assert len(word) >= 3, f"Expected word length >= 3, got: {word!r}"


def test_generate_number_range(db_session):
    account_id = generate_account_id_unique(db_session)

    number_str = account_id.rsplit("-", 1)[-1]
    assert len(number_str) == 4, f"Expected 4-digit zero-padded number, got: {number_str!r}"
    number = int(number_str)
    assert 0 <= number <= 9999
