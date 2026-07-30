from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from store.api.remnawave import api as remnawave_api
from store.services.integrations import _blocked, decrypt_secret, encrypt_secret


def test_ssrf_network_filter_blocks_private_and_metadata() -> None:
    for address in ("127.0.0.1", "10.0.0.2", "169.254.169.254", "192.168.1.1", "::1", "fe80::1"):
        assert _blocked(address)
    assert not _blocked("1.1.1.1")


def test_integration_secret_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv("STORE_MASTER_KEY", "test-only-master-key")
    ciphertext, nonce = encrypt_secret("sensitive-value")
    assert b"sensitive-value" not in ciphertext
    assert decrypt_secret(ciphertext, nonce) == "sensitive-value"


def test_email_finalizer_updates_only_uuid_and_email(monkeypatch) -> None:
    captured = {}

    class Users:
        async def update_user(self, request):
            captured.update(request.model_dump(exclude_none=True))
            return SimpleNamespace(
                uuid=request.uuid,
                email=request.email,
                subscription_url="https://subscription.example/test",
            )

    monkeypatch.setattr(remnawave_api, "get_sdk", lambda: SimpleNamespace(users=Users()))
    user_uuid = uuid.uuid4()
    result = asyncio.run(remnawave_api.update_user_email(str(user_uuid), "buyer@example.com"))
    assert set(captured) == {"uuid", "email"}
    assert captured["uuid"] == user_uuid
    assert result["email"] == "buyer@example.com"
