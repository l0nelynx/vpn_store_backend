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
- Remnawave 3 users are stored by numeric `id`; the removed legacy UUID remains read-only historical data.
- Existing users are resolved by stable username and extended through `POST /api/users/{userId}/actions/extend`.
- New orders keep usernames `gg_id{content_id}` / `dig_id{inv}`
