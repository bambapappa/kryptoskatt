"""Tests for secrets service — encryption at rest for user secrets."""

from unittest.mock import patch

from kryptoskatt.services import secrets as secrets_module
from kryptoskatt.services.secrets import decrypt_secret, encrypt_secret


class TestWithSecretKey:
    def test_roundtrip(self):
        with patch.object(secrets_module.settings, "secret_key", "test-instance-key"):
            stored = encrypt_secret("my-api-key-123")
            assert stored != "my-api-key-123"
            assert stored.startswith("enc:v1:")
            assert decrypt_secret(stored) == "my-api-key-123"

    def test_empty_and_none_pass_through(self):
        with patch.object(secrets_module.settings, "secret_key", "test-instance-key"):
            assert encrypt_secret("") == ""
            assert encrypt_secret(None) is None
            assert decrypt_secret("") == ""
            assert decrypt_secret(None) == ""

    def test_legacy_plaintext_passes_through_decrypt(self):
        with patch.object(secrets_module.settings, "secret_key", "test-instance-key"):
            assert decrypt_secret("legacy-plaintext-key") == "legacy-plaintext-key"

    def test_wrong_key_returns_empty(self):
        with patch.object(secrets_module.settings, "secret_key", "key-one"):
            stored = encrypt_secret("secret-value")
        with patch.object(secrets_module.settings, "secret_key", "key-two"):
            assert decrypt_secret(stored) == ""


class TestWithoutSecretKey:
    def test_encrypt_falls_back_to_plaintext(self):
        with patch.object(secrets_module.settings, "secret_key", ""):
            assert encrypt_secret("my-api-key") == "my-api-key"

    def test_decrypt_of_encrypted_value_without_key_returns_empty(self):
        with patch.object(secrets_module.settings, "secret_key", "some-key"):
            stored = encrypt_secret("val")
        with patch.object(secrets_module.settings, "secret_key", ""):
            assert decrypt_secret(stored) == ""
