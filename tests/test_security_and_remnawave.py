from __future__ import annotations

import asyncio
import datetime
from types import SimpleNamespace

import pytest

from store.api.remnawave import api as remnawave_api
from store.api.remnawave.users_bulk import _normalize_user
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


def test_email_finalizer_updates_only_numeric_id_and_email(monkeypatch) -> None:
    captured = {}

    class Users:
        async def update_user(self, request):
            captured.update(request.model_dump(exclude_none=True))
            return SimpleNamespace(
                id=request.id,
                email=request.email,
                subscription_url="https://subscription.example/test",
            )

    monkeypatch.setattr(remnawave_api, "get_sdk", lambda: SimpleNamespace(users=Users()))
    result = asyncio.run(remnawave_api.update_user_email(123, "buyer@example.com"))
    assert set(captured) == {"id", "email"}
    assert captured["id"] == 123
    assert result["email"] == "buyer@example.com"


def test_extend_user_uses_v3_atomic_endpoint(monkeypatch) -> None:
    captured = {}

    class Users:
        async def extend_user(self, user_id, request):
            captured["user_id"] = user_id
            captured.update(request.model_dump())
            return SimpleNamespace(
                id=user_id,
                expire_at=datetime.datetime.now(datetime.timezone.utc),
                subscription_url="https://subscription.example/test",
                status=remnawave_api.UserStatus.ACTIVE,
            )

    monkeypatch.setattr(remnawave_api, "get_sdk", lambda: SimpleNamespace(users=Users()))
    result = asyncio.run(remnawave_api.extend_user(321, 30))

    assert captured == {"user_id": 321, "days": 30}
    assert result["id"] == 321


def test_v3_user_ids_are_numeric_and_bulk_normalization_drops_uuid() -> None:
    with pytest.raises(ValueError):
        remnawave_api._as_user_id("7d743bf8-e2f2-4a98-8d79-6de45b5cd443")

    normalized = _normalize_user({
        "id": 456,
        "username": "gg_id123",
        "subscriptionUrl": "https://subscription.example/test",
        "status": "ACTIVE",
    })
    assert normalized["id"] == 456
    assert "uuid" not in normalized
