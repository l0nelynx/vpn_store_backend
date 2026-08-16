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

    inferred = adapter.money_fields({"amount": "3.50", "amount_usd": "3.50"})
    assert inferred["currency"] == "USD"

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

        class _Fx:
            id = 7
            rate = Decimal("83.9971")
            base_currency = "USD"

        class _FxSession:
            async def get(self, *_args, **_kwargs):
                return None

            async def scalar(self, *_args, **_kwargs):
                return _Fx()

        converted = await _quote_order_money(
            _FxSession(),
            gross_amount="3.50",
            net_amount="5",
            amount_usd="3.50",
            currency="RUB",
        )
        assert converted["currency"] == "USD"
        assert converted["net_rub"] == Decimal("3.50") * Decimal("83.9971")

    asyncio.run(run())


def test_fx_json_and_unconverted_usd_detection() -> None:
    from types import SimpleNamespace

    from store.domain.money import looks_unconverted_usd, parse_jsdelivr_usd_json, parse_open_er_api_json, quote_order_revenue_rub
    from store.services.fx import order_revenue_rub

    jsdelivr = {"date": "2026-08-15", "usd": {"rub": "83.9971", "eur": "0.8644"}}
    day, rates = parse_jsdelivr_usd_json(jsdelivr)
    assert day.isoformat() == "2026-08-15"
    assert rates["USD"] == Decimal("83.9971")
    assert rates["EUR"] == Decimal("83.9971") / Decimal("0.8644")
    assert looks_unconverted_usd("5", "3.50")
    assert looks_unconverted_usd("3.50", "3.50")
    assert not looks_unconverted_usd("293.99", "3.50")

    rate = Decimal("83.9851108")
    assert quote_order_revenue_rub(
        net_rub="5", amount="5", amount_usd="3.50", currency="RUB", usd_rate=rate
    ) == Decimal("3.50") * rate
    assert quote_order_revenue_rub(
        net_rub="0", amount="3.50", currency="USD", usd_rate=rate
    ) == Decimal("3.50") * rate
    assert quote_order_revenue_rub(
        net_rub=None, amount="3.50", currency="WMZ", usd_rate=rate
    ) == Decimal("3.50") * rate
    assert quote_order_revenue_rub(
        net_rub="293.99", amount_usd="3.50", currency="RUB", usd_rate=rate
    ) == Decimal("293.99")
    assert quote_order_revenue_rub(
        net_rub="142.50", profit_amount="142.50", currency="WMR", amount_usd="1.60", usd_rate=rate
    ) == Decimal("142.50")
    assert order_revenue_rub(
        SimpleNamespace(
            net_rub=Decimal("0"),
            profit_amount=None,
            net_amount=Decimal("3.50"),
            gross_amount=Decimal("3.50"),
            amount=Decimal("3.50"),
            amount_usd=None,
            currency="RUB",
            net_currency="RUB",
            raw={"amount": "3.50", "type_curr": "WMZ"},
        ),
        rate,
        None,
    ) == Decimal("3.50") * rate

    open_er = {
        "time_last_update_utc": "Sun, 16 Aug 2026 00:02:31 +0000",
        "rates": {"USD": 1, "RUB": 83.574704, "EUR": 0.864749},
    }
    day, rates = parse_open_er_api_json(open_er)
    assert day.isoformat() == "2026-08-16"
    assert rates["USD"] == Decimal("83.574704")


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
