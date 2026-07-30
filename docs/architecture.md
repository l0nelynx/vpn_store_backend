# Architecture notes

See the implementation plan. Summary:

- PostgreSQL-only data layer + Admin SPA — **xray-vpn-bot is not modified**
- Remnawave is the shared subscription source of truth
- Digiseller / GGSel APIs are normalized by provider-specific adapters
- FastAPI handles synchronous webhooks; the worker handles polling, continuation,
  retries, finalizers and dead-letter jobs via a PostgreSQL outbox
- Bot CRM leftover delivery: documented in `docs/bot_crm_integration.md`

## Fulfillment renew policy

- Idempotent on `(marketplace, provider_order_id)` and per-step idempotency keys
- If order already provisioned: return existing URL (resend delivery if needed), **no double-extend**
- If Remnawave username exists without a local delivered order: **extend** `expire_at` by `days` from `max(now, current_expire)`
- New orders keep usernames `gg_id{content_id}` / `dig_id{inv}`
