# VPN Store Backend

Marketplace order fulfillment (Digiseller + GGsel) → Remnawave provisioning,
plus Store Admin for products, mappings, customers, and chats.

## Quick start

1. Copy `backend.example.yml` → `backend.yml` and fill secrets.
2. Optional Postgres: set `database_url: postgresql+asyncpg://store:store@localhost:5433/store`
   (or omit for SQLite `db/backend_db.sqlite3`).
3. `pip install -r requirements.txt`
4. `python store_backend.py`
5. Admin SPA: `cd admin && npm install && npm run build` → served at `/store/admin/`

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
