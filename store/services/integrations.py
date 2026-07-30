"""Encrypted integration secrets and SSRF-safe generic HTTP execution."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import socket
from base64 import urlsafe_b64encode
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from store.database.models import IntegrationProfile, IntegrationSecret, async_session
from store.domain.pipeline import PipelineError, extract_outputs, render_value
from store.settings import secrets


BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16",
        "198.18.0.0/15", "224.0.0.0/4", "::/128", "::1/128", "fc00::/7", "fe80::/10",
    )
)


def _master_key() -> bytes:
    value = os.getenv("STORE_MASTER_KEY") or secrets.get("master_key")
    if not value:
        raise RuntimeError("STORE_MASTER_KEY is required for integration secrets")
    return hashlib.sha256(str(value).encode()).digest()


def encrypt_secret(value: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_master_key()).encrypt(nonce, value.encode(), b"store-integration-secret-v1")
    return ciphertext, nonce


def decrypt_secret(ciphertext: bytes, nonce: bytes) -> str:
    return AESGCM(_master_key()).decrypt(nonce, ciphertext, b"store-integration-secret-v1").decode()


def _blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(ip in network for network in BLOCKED_NETWORKS) or not ip.is_global


async def resolve_public(host: str, port: int) -> list[str]:
    try:
        rows = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise PipelineError("dns_failed", f"Could not resolve integration host: {host}") from exc
    addresses = sorted({row[4][0] for row in rows})
    if not addresses or any(_blocked(address) for address in addresses):
        raise PipelineError("ssrf_blocked", "Integration host resolves to a blocked network", permanent=True)
    return addresses


class PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, host: str, addresses: list[str]):
        self.host = host
        self.addresses = addresses

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[dict[str, Any]]:
        if host != self.host:
            raise OSError("Unexpected DNS lookup")
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": socket.IPPROTO_TCP,
                "flags": socket.AI_NUMERICHOST,
            }
            for address in self.addresses
        ]

    async def close(self) -> None:
        return None


async def profile_secrets(profile_id: int) -> dict[str, str]:
    async with async_session() as session:
        rows = (
            await session.scalars(select(IntegrationSecret).where(IntegrationSecret.profile_id == profile_id))
        ).all()
        return {row.name: decrypt_secret(row.ciphertext, row.nonce) for row in rows}


async def save_profile_secret(profile_id: int, name: str, value: str) -> None:
    ciphertext, nonce = encrypt_secret(value)
    async with async_session() as session:
        row = await session.scalar(
            select(IntegrationSecret).where(
                IntegrationSecret.profile_id == profile_id,
                IntegrationSecret.name == name,
            )
        )
        if row:
            row.ciphertext, row.nonce = ciphertext, nonce
        else:
            session.add(IntegrationSecret(profile_id=profile_id, name=name, ciphertext=ciphertext, nonce=nonce))
        await session.commit()


def _auth_headers(profile: IntegrationProfile, values: dict[str, str]) -> tuple[dict[str, str], aiohttp.BasicAuth | None]:
    config = profile.auth_config or {}
    if profile.auth_type == "bearer":
        return {"Authorization": f"Bearer {values[config.get('secret_name', 'token')]}"}, None
    if profile.auth_type == "api_key":
        return {str(config.get("header", "X-API-Key")): values[config.get("secret_name", "api_key")]}, None
    if profile.auth_type == "basic":
        return {}, aiohttp.BasicAuth(
            values[config.get("username_secret", "username")],
            values[config.get("password_secret", "password")],
        )
    return {}, None


async def execute_http_action(
    *, profile_id: int, config: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    async with async_session() as session:
        profile = await session.get(IntegrationProfile, profile_id)
        if not profile or not profile.enabled:
            raise PipelineError("integration_unavailable", "Integration profile is disabled or missing", permanent=True)

    rendered = render_value(config, context)
    relative_path = str(rendered.get("path") or "")
    if urlparse(relative_path).scheme or relative_path.startswith("//"):
        raise PipelineError("absolute_url_forbidden", "HTTP action path must be relative", permanent=True)
    base = profile.base_url.rstrip("/") + "/"
    url = urljoin(base, relative_path.lstrip("/"))
    parsed_base, parsed = urlparse(profile.base_url), urlparse(url)
    if parsed.scheme not in {"https", "http"} or parsed.hostname != parsed_base.hostname:
        raise PipelineError("host_escape", "Rendered path escapes integration host", permanent=True)
    allowed = set(profile.allowed_hosts or [])
    if parsed.hostname not in allowed:
        raise PipelineError("host_not_allowed", "Integration host is not in the allowlist", permanent=True)

    values = await profile_secrets(profile.id)
    if any(secret and secret in url for secret in values.values()):
        raise PipelineError("secret_in_url", "Secrets are forbidden in URLs", permanent=True)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await resolve_public(parsed.hostname or "", port)
    auth_headers, basic_auth = _auth_headers(profile, values)
    headers = {str(k): str(v) for k, v in (rendered.get("headers") or {}).items()}
    headers.update(auth_headers)
    if rendered.get("_idempotency_key"):
        header_name = str(rendered.get("idempotency_header") or "Idempotency-Key")
        headers[header_name] = str(rendered["_idempotency_key"])
    method = str(rendered.get("method", "GET")).upper()
    kwargs: dict[str, Any] = {
        "params": rendered.get("query") or None,
        "headers": headers,
        "auth": basic_auth,
        "allow_redirects": False,
    }
    body_type = rendered.get("body_type", "json")
    if "body" in rendered:
        kwargs[{"json": "json", "text": "data", "form": "data"}.get(body_type, "json")] = rendered["body"]
    timeout = aiohttp.ClientTimeout(total=float(rendered.get("timeout_seconds") or 10))
    connector = aiohttp.TCPConnector(
        resolver=PinnedResolver(parsed.hostname or "", addresses), ttl_dns_cache=0
    )
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as http:
            async with http.request(method, url, **kwargs) as response:
                status = response.status
                body_text = await response.text()
                content_type = response.headers.get("Content-Type", "")
                body_json = None
                if "json" in content_type and body_text:
                    try:
                        body_json = json.loads(body_text)
                    except ValueError:
                        body_json = None
    except asyncio.TimeoutError as exc:
        raise PipelineError("ambiguous_timeout", "External API timed out") from exc
    expected = rendered.get("expected_statuses") or list(range(200, 300))
    if status not in expected:
        raise PipelineError("unexpected_status", f"External API returned HTTP {status}")
    outputs = {
        "status_code": status,
        "success": True,
        "body_text": body_text,
    }
    if body_json is not None:
        outputs["body_json"] = body_json
        outputs.update(extract_outputs(body_json, rendered.get("outputs") or {}))
    for output in outputs.values():
        rendered_output = json.dumps(output, ensure_ascii=False, default=str)
        if any(secret and secret in rendered_output for secret in values.values()):
            raise PipelineError("secret_in_output", "An extracted output contains a secret", permanent=True)
    return outputs
