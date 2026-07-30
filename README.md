# VPN Store Backend

Universal marketplace fulfillment (Digiseller + GGSel) with versioned Delivery
Pipelines, Remnawave provisioning, generic HTTP actions and Store Admin.

## Quick start

1. Copy `backend.example.yml` → `backend.yml` and fill secrets.
2. Configure PostgreSQL (it is the only supported database). In Docker use
   `database_url: postgresql+asyncpg://store:store@store-postgres:5432/store`
   (the local host bind is `127.0.0.1:5433`).
   Compose passes the internal DSN explicitly to API, worker and migrations.
   Override it only through `STORE_DOCKER_DATABASE_URL`; do not use a host
   `127.0.0.1:5433` URL inside containers.
   Do **not** name the DB service `postgres` on the shared `backend-network` —
   xray-vpn-bot dual-homed containers would resolve that hostname to the wrong DB.
3. `docker compose up -d` runs migrations, API and worker as separate processes.
4. Admin SPA: `cd admin && pnpm install && pnpm run build` → served at `/store/admin/`

Legacy products with an explicit `order_params.marketplace` are backfilled into
active bindings and receive the published compatibility pipeline automatically.
Rows without a marketplace remain `needs_configuration` and must be assigned in
Store Admin because their provider cannot be inferred safely.

During rollout Compose also runs the idempotent `store-legacy-import` job after
Alembic. If `db/backend_db.sqlite3` exists, it is mounted read-only and its
`order_params`, `param_value_mappings` and `product_option_labels` are copied to
PostgreSQL before the API and worker start. Repeated runs do not duplicate data.

## Docs

- [Order Params API](docs/order_params_api.md) — dashboard-compatible mapping CRUD
- [Bot CRM integration](docs/bot_crm_integration.md) — future leftover broadcast handoff (bot code unchanged)

## Key endpoints

| Path | Role |
|------|------|
| `POST /store/digiseller_webhook` | Digiseller fulfillment |
| `POST /store/ggsel_webhook_new` | Compatibility notify (worker verifies through Seller API V1) |
| `/store/api/v1/*` | Products, pipelines, runs, templates, integrations, analytics and audit |
| `/store/api/order-params/` | Mapping CRUD (Bearer `api_token`) |
| `/store/api/admin/*` | Admin SPA API |
| `/store/api/messages/*` | Inbox sync/send |
| `/store/internal/crm/*` | resolve / broadcast for bot CRM |
| `/store/admin/` | Admin SPA static |
