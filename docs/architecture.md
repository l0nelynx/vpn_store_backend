# Architecture notes

See the implementation plan. Summary:

- Own Postgres (or SQLite) + Admin SPA — **xray-vpn-bot is not modified**
- Remnawave is the shared subscription source of truth
- Digiseller / GGsel APIs are consumed only by this service
- Bot CRM leftover delivery: documented in `docs/bot_crm_integration.md`

## Fulfillment renew policy

- Idempotent on `(marketplace, external_order_id)`
- If order already provisioned: return existing URL (resend delivery if needed), **no double-extend**
- If Remnawave username exists without a local delivered order: **extend** `expire_at` by `days` from `max(now, current_expire)`
- New orders keep usernames `gg_id{content_id}` / `dig_id{inv}`
