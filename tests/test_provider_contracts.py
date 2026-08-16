from __future__ import annotations

import hashlib
import asyncio
import json
from decimal import Decimal

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


def test_digiseller_money_fields_use_profit_and_wmr_as_rub() -> None:
    adapter = DigisellerAdapter()
    fields = adapter.money_fields({
        "id": 42,
        "inv": 9001,
        "amount": "150.00",
        "profit": "142.50",
        "type_curr": "WMR",
        "amount_usd": "1.60",
    })
    assert fields["gross_amount"] == "150.00"
    assert fields["net_amount"] == "142.50"
    assert fields["profit_amount"] == "142.50"
    assert fields["currency"] == "RUB"
    assert fields["gross_currency"] == "RUB"
    assert fields["net_currency"] == "RUB"
    assert fields["amount_usd"] == "1.60"


def test_digiseller_money_fields_fallback_to_amount_and_nested_content() -> None:
    adapter = DigisellerAdapter()
    webhook = adapter.money_fields({"amount": 200, "type_curr": "RUR"})
    assert webhook["net_amount"] == 200
    assert webhook["profit_amount"] is None
    assert webhook["currency"] == "RUB"

    nested = adapter.money_fields({
        "content": {"amount": 80, "profit": "", "currency": "WMZ"},
    })
    assert nested["gross_amount"] == 80
    assert nested["net_amount"] == 80
    assert nested["currency"] == "USD"

    partner = adapter.money_fields({"amount": "100", "agent_percent": 10, "type_curr": "RUB"})
    assert partner["net_amount"] == Decimal("90")
    assert partner["profit_amount"] is None


def test_quote_order_money_maps_wmr_profit_to_net_rub() -> None:
    from store.services.runtime import _quote_order_money

    class _Session:
        async def get(self, *_args, **_kwargs):
            return None

        async def scalar(self, *_args, **_kwargs):
            return None

    async def run():
        quoted = await _quote_order_money(
            _Session(),
            gross_amount="150.00",
            net_amount="142.50",
            profit_amount="142.50",
            currency="WMR",
        )
        assert quoted["currency"] == "RUB"
        assert quoted["gross_rub"] == Decimal("150.00")
        assert quoted["net_rub"] == Decimal("142.50")
        assert quoted["net_amount"] == Decimal("142.50")

        fallback = await _quote_order_money(_Session(), gross_amount="80", currency="RUR")
        assert fallback["net_rub"] == Decimal("80")
        assert fallback["profit_amount"] is None

    asyncio.run(run())


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
