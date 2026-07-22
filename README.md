# VPN Store Backend

Marketplace order fulfillment (Digiseller + GGsel) → Remnawave provisioning,
plus Store Admin for products, mappings, customers, and chats.

## Quick start

1. Copy `backend.example.yml` → `backend.yml` and fill secrets.
2. Optional Postgres: in Docker use
   `database_url: postgresql+asyncpg://store:store@store-postgres:5432/store`
   (host bind is `127.0.0.1:5433`; omit `database_url` for SQLite).
   Do **not** name the DB service `postgres` on the shared `backend-network` —
   xray-vpn-bot dual-homed containers would resolve that hostname to the wrong DB.
3. `docker compose up -d` (or `pip install -r requirements.txt` + `python store_backend.py`)
4. Admin SPA: `cd admin && npm install && npm run build` → served at `/store/admin/`

## Docs

- [Order Params API](docs/order_params_api.md) — dashboard-compatible mapping CRUD
- [Bot CRM integration](docs/bot_crm_integration.md) — future leftover broadcast handoff (bot code unchanged)

## Key endpoints

| Path | Role |
|------|------|
| `POST /store/digiseller_webhook` | Digiseller fulfillment |
| `POST /store/ggsel_webhook_new` | GGsel notify + fulfill |
| `/store/api/order-params/` | Mapping CRUD (Bearer `api_token`) |
| `/store/api/admin/*` | Admin SPA API |
| `/store/api/messages/*` | Inbox sync/send |
| `/store/internal/crm/*` | resolve / broadcast for bot CRM |
| `/store/admin/` | Admin SPA static |
