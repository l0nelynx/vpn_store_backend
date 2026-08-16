"""Official GGSel V1 and Digiseller API adapters.

Raw numeric states never escape these adapters.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import aiohttp

from store.settings import secrets

# Digiseller type_curr uses WebMoney ticker codes, not ISO-4217.
CURRENCY_ALIASES = {
    "WMR": "RUB",
    "RUR": "RUB",
    "RUB": "RUB",
    "WMZ": "USD",
    "USD": "USD",
    "WME": "EUR",
    "EUR": "EUR",
}


def canonical_currency(raw: Any) -> str | None:
    if raw in (None, ""):
        return None
    code = str(raw).strip().upper()
    return CURRENCY_ALIASES.get(code, code)


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, temporary: bool = True):
        super().__init__(message)
        self.status = status
        self.temporary = temporary


class _TokenCache:
    def __init__(self) -> None:
        self.token: str | None = None
        self.valid_until = 0.0
        self.lock = asyncio.Lock()

    def valid(self) -> bool:
        return bool(self.token and self.valid_until > time.time() + 60)

    def set(self, payload: dict[str, Any], default_ttl: int = 3600) -> str:
        token = str(payload["token"])
        raw = payload.get("valid_thru") or payload.get("valid_until")
        valid_until = time.time() + default_ttl
        if raw:
            try:
                valid_until = float(raw)
            except (TypeError, ValueError):
                try:
                    valid_until = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
        self.token, self.valid_until = token, valid_until
        return token

    def clear(self) -> None:
        self.token, self.valid_until = None, 0


class GGSelAdapter:
    provider = "ggsel"
    state_map = {1: "created", 2: "cancelled", 3: "paid", 4: "fulfilled", 5: "returned"}

    def __init__(self) -> None:
        self.base_url = (secrets.get("ggsel_base_url") or "https://seller.ggsel.com").rstrip("/")
        self.seller_id = str(secrets.get("ggsel_seller_id") or "")
        self.api_key = str(secrets.get("ggsel_api_key") or "")
        self.cache = _TokenCache()
        self._last_timestamp_us = 0

    def normalize_state(self, raw: int | str | None) -> str:
        try:
            return self.state_map.get(int(raw), "unknown")
        except (TypeError, ValueError):
            return "unknown"

    async def token(self, http: aiohttp.ClientSession, force: bool = False) -> str:
        if self.cache.valid() and not force:
            return self.cache.token or ""
        async with self.cache.lock:
            if self.cache.valid() and not force:
                return self.cache.token or ""
            now_us = time.time_ns() // 1_000
            self._last_timestamp_us = max(now_us, self._last_timestamp_us + 1)
            seconds, micros = divmod(self._last_timestamp_us, 1_000_000)
            timestamp = f"{seconds}.{micros:06d}"
            sign = hashlib.sha256(f"{self.api_key}{timestamp}".encode()).hexdigest()
            async with http.post(
                f"{self.base_url}/api_sellers/api/apilogin",
                json={"seller_id": self.seller_id, "timestamp": timestamp, "sign": sign},
                headers={"Accept": "application/json"},
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400 or not isinstance(data, dict) or not data.get("token"):
                    raise ProviderError("GGSel authentication failed", status=response.status)
                return self.cache.set(data, default_ttl=3600)

    async def _request(self, http: aiohttp.ClientSession, method: str, path: str, **kwargs) -> Any:
        base_params = dict(kwargs.pop("params", {}) or {})
        for attempt in range(2):
            token = await self.token(http, force=attempt == 1)
            params = dict(base_params)
            params["token"] = token
            async with http.request(method, f"{self.base_url}/api_sellers/api{path}", params=params, **kwargs) as response:
                if response.status == 401 and attempt == 0:
                    self.cache.clear()
                    continue
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise ProviderError(f"GGSel HTTP {response.status}", status=response.status)
                return data
        raise ProviderError("GGSel authorization retry exhausted")

    async def recent_sales(self, http: aiohttp.ClientSession, top: int = 50) -> list[dict]:
        data = await self._request(http, "GET", "/seller-last-sales", params={"seller_id": self.seller_id, "top": top})
        return data.get("sales") or []

    async def seller_goods(self, http: aiohttp.ClientSession) -> list[dict]:
        data = await self._request(
            http, "POST", "/seller-goods",
            json={"seller_id": self.seller_id, "page": 1, "rows": 1000, "show_hidden": 1},
        )
        rows = data.get("rows") or data.get("goods") or data.get("retval") or []
        return list(rows.values()) if isinstance(rows, dict) else rows

    async def purchase(self, http: aiohttp.ClientSession, invoice_id: str | int) -> dict:
        return await self._request(http, "GET", f"/purchase/info/{invoice_id}")

    async def send_message(self, http: aiohttp.ClientSession, content_id: str | int, message: str) -> None:
        await self._request(http, "POST", "/debates/v2", params={"id_i": content_id}, json={"message": message})

    async def chats(
        self,
        http: aiohttp.ClientSession,
        *,
        filter_new: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        params: dict[str, Any] = {"page": page, "pagesize": page_size, "pageSize": page_size}
        if filter_new:
            params["filter_new"] = 1
        data = await self._request(http, "GET", "/debates/v2/chats", params=params)
        rows = data if isinstance(data, list) else data.get("chats") or data.get("items") or []
        if filter_new:
            rows = [row for row in rows if int(row.get("cnt_new") or 0) > 0]
        return rows

    async def messages(self, http: aiohttp.ClientSession, content_id: str | int, count: int = 50) -> list[dict]:
        data = await self._request(http, "GET", "/debates/v2", params={"id_i": content_id, "count": count})
        return data if isinstance(data, list) else data.get("items") or data.get("messages") or []

    async def mark_seen(self, http: aiohttp.ClientSession, content_id: str | int) -> None:
        """Best-effort read flag; GGSel may not expose Digiseller's /seen endpoint."""
        try:
            await self._request(http, "POST", "/debates/v2/seen", params={"id_i": content_id}, json={})
        except ProviderError:
            # Empty body or unsupported endpoint should not break inbox open.
            pass


class DigisellerAdapter:
    provider = "digiseller"
    state_map = {1: "waiting", 2: "cancelled", 3: "paid", 4: "overdue", 5: "refund", 35: "refund"}

    def __init__(self) -> None:
        self.base_url = (secrets.get("dig_url") or "https://api.digiseller.com").rstrip("/")
        self.seller_id = str(secrets.get("dig_seller_id") or "")
        self.api_key = str(secrets.get("dig_api_key") or "")
        self.cache = _TokenCache()
        self._last_timestamp = 0

    def normalize_state(self, raw: int | str | None) -> str:
        try:
            return self.state_map.get(int(raw), "unknown")
        except (TypeError, ValueError):
            return "unknown"

    def normalize_currency(self, raw: Any) -> str | None:
        return canonical_currency(raw)

    def money_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Gross/net amounts for analytics. Profit is net of commissions when present."""
        content = payload.get("content") if isinstance(payload.get("content"), dict) else {}

        def pick(*keys: str) -> Any:
            for source in (payload, content):
                if not isinstance(source, dict):
                    continue
                for key in keys:
                    value = source.get(key)
                    if value not in (None, ""):
                        return value
            return None

        amount = pick("amount")
        profit = pick("profit")
        net: Any = profit
        if net is None and amount is not None:
            net = amount
            agent_percent = pick("agent_percent")
            if agent_percent not in (None, ""):
                try:
                    percent = Decimal(str(agent_percent))
                    if percent > 0:
                        net = Decimal(str(amount)) * (Decimal("100") - percent) / Decimal("100")
                except (InvalidOperation, ValueError):
                    pass
        currency = self.normalize_currency(pick("type_curr", "currency", "currency_type")) or "RUB"
        return {
            "gross_amount": amount,
            "net_amount": net,
            "profit_amount": profit,
            "amount_usd": pick("amount_usd"),
            "currency": currency,
            "gross_currency": currency,
            "net_currency": currency,
        }

    def valid_supplier_signature(self, payload: dict[str, Any]) -> bool:
        password = str(secrets.get("dig_pass") or "")
        expected = hashlib.md5(f"{payload.get('id')}:{payload.get('inv')}:{password}".encode()).hexdigest()
        import hmac
        return hmac.compare_digest(str(payload.get("sign") or "").lower(), expected.lower())

    async def token(self, http: aiohttp.ClientSession, force: bool = False) -> str:
        if self.cache.valid() and not force:
            return self.cache.token or ""
        async with self.cache.lock:
            if self.cache.valid() and not force:
                return self.cache.token or ""
            timestamp = max(int(time.time()), self._last_timestamp + 1)
            self._last_timestamp = timestamp
            sign = hashlib.sha256(f"{self.api_key}{timestamp}".encode()).hexdigest()
            async with http.post(
                f"{self.base_url}/api/apilogin",
                json={"seller_id": int(self.seller_id), "timestamp": timestamp, "sign": sign},
                headers={"Accept": "application/json"},
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400 or not isinstance(data, dict) or not data.get("token"):
                    raise ProviderError("Digiseller authentication failed", status=response.status)
                return self.cache.set(data, default_ttl=7200)

    async def _request(self, http: aiohttp.ClientSession, method: str, path: str, **kwargs) -> Any:
        base_params = dict(kwargs.pop("params", {}) or {})
        for attempt in range(2):
            token = await self.token(http, force=attempt == 1)
            params = dict(base_params)
            params["token"] = token
            async with http.request(method, f"{self.base_url}/api{path}", params=params, **kwargs) as response:
                if response.status == 401 and attempt == 0:
                    self.cache.clear()
                    continue
                raw = await response.read()
                if response.status >= 400:
                    raise ProviderError(f"Digiseller HTTP {response.status}", status=response.status)
                if not raw.strip():
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"Digiseller invalid JSON: {exc}", status=response.status) from exc
        raise ProviderError("Digiseller authorization retry exhausted")

    async def purchase(self, http: aiohttp.ClientSession, inv: str | int) -> dict:
        return await self._request(http, "GET", f"/purchase/info/{inv}")

    async def seller_goods(self, http: aiohttp.ClientSession) -> list[dict]:
        data = await self._request(
            http, "POST", "/seller-goods",
            json={"id_seller": int(self.seller_id), "page": 1, "rows": 1000, "currency": "RUR", "lang": "ru-RU", "show_hidden": 1},
        )
        rows = data.get("rows") or data.get("retval") or data.get("goods") or []
        if isinstance(rows, dict):
            rows = rows.get("row") or rows.get("goods") or []
        return rows if isinstance(rows, list) else []

    async def send_message(self, http: aiohttp.ClientSession, inv: str | int, message: str) -> None:
        await self._request(http, "POST", "/debates/v2", params={"id_i": inv}, json={"message": message, "files": []})

    async def chats(
        self,
        http: aiohttp.ClientSession,
        *,
        filter_new: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "page": page,
            "pagesize": page_size,
            "pageSize": page_size,
            "filter_new": 1 if filter_new else 0,
        }
        data = await self._request(http, "GET", "/debates/v2/chats", params=params)
        rows = data if isinstance(data, list) else data.get("chats") or data.get("items") or []
        if filter_new:
            rows = [row for row in rows if int(row.get("cnt_new") or 0) > 0]
        return rows

    async def messages(self, http: aiohttp.ClientSession, inv: str | int, count: int = 50) -> list[dict]:
        data = await self._request(http, "GET", "/debates/v2", params={"id_i": inv, "count": count})
        return data if isinstance(data, list) else data.get("items") or data.get("messages") or []

    async def mark_seen(self, http: aiohttp.ClientSession, inv: str | int) -> None:
        await self._request(http, "POST", "/debates/v2/seen", params={"id_i": inv}, json={})

    async def permissions(self, http: aiohttp.ClientSession) -> dict[str, Any]:
        # Official Digiseller endpoint: GET /api/token/perms?token=...
        path = str(secrets.get("dig_permissions_path") or "/token/perms")
        data = await self._request(http, "GET", path)
        return data if isinstance(data, dict) else {"permissions": data}


ggsel = GGSelAdapter()
digiseller = DigisellerAdapter()
