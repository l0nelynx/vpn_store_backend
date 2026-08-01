from __future__ import annotations

import hashlib
import asyncio
import json

from store.integrations.providers import DigisellerAdapter, GGSelAdapter
from store.services.order_sync import _ggsel_order_content
from store.settings import secrets


class _Response:
    def __init__(self, status: int, payload: dict):
        self.status, self.payload = status, payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self, **_kwargs):
        return self.payload

    async def read(self):
        return json.dumps(self.payload).encode()


class _RequestHttp:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _Response(401 if len(self.calls) == 1 else 200, {"ok": True})


class _LoginHttp:
    def __init__(self):
        self.payloads = []

    def post(self, _url, **kwargs):
        self.payloads.append(kwargs["json"])
        return _Response(200, {"token": f"token-{len(self.payloads)}", "valid_thru": 1})


def test_provider_state_normalization_is_adapter_specific() -> None:
    ggsel = GGSelAdapter()
    digiseller = DigisellerAdapter()
    assert [ggsel.normalize_state(value) for value in (3, 4, 5)] == ["paid", "fulfilled", "returned"]
    assert [digiseller.normalize_state(value) for value in (3, 4, 5, 35)] == [
        "paid", "overdue", "refund", "refund"
    ]


def test_ggsel_purchase_info_keeps_invoice_and_content_ids_separate() -> None:
    payload = {
        "retval": 0,
        "content": {
            "item_id": 5422669,
            "content_id": 987654,
            "invoice_state": 4,
        },
    }
    content = _ggsel_order_content(payload, 40941008)
    assert content["invoice_id"] == 40941008
    assert content["content_id"] == 987654


def test_digiseller_supplier_signature(monkeypatch) -> None:
    monkeypatch.setitem(secrets, "dig_pass", "supplier-secret")
    adapter = DigisellerAdapter()
    payload = {"id": 42, "inv": 9001}
    payload["sign"] = hashlib.md5(b"42:9001:supplier-secret").hexdigest()
    assert adapter.valid_supplier_signature(payload)
    payload["sign"] = "0" * 32
    assert not adapter.valid_supplier_signature(payload)


def test_401_refresh_keeps_original_query_parameters() -> None:
    async def scenario(adapter):
        issued = []

        async def token(_http, force=False):
            issued.append(force)
            return "refreshed" if force else "initial"

        adapter.token = token
        http = _RequestHttp()
        result = await adapter._request(http, "POST", "/debates/v2", params={"id_i": 77}, json={"message": "ok"})
        assert result == {"ok": True}
        assert [call[2]["params"]["id_i"] for call in http.calls] == [77, 77]
        assert [call[2]["params"]["token"] for call in http.calls] == ["initial", "refreshed"]
        assert issued == [False, True]

    asyncio.run(scenario(GGSelAdapter()))
    asyncio.run(scenario(DigisellerAdapter()))


def test_parallel_logins_never_reuse_timestamp() -> None:
    async def scenario(adapter):
        adapter.seller_id, adapter.api_key = "1", "key"
        http = _LoginHttp()
        await asyncio.gather(adapter.token(http, force=True), adapter.token(http, force=True))
        timestamps = [payload["timestamp"] for payload in http.payloads]
        assert len(timestamps) == len(set(timestamps)) == 2

    asyncio.run(scenario(GGSelAdapter()))
    asyncio.run(scenario(DigisellerAdapter()))
