# Bot CRM ↔ Store integration guide

This document describes how **xray-vpn-bot** CRM can later hand leftover
Remnawave recipients to **vpn_store_backend** for delivery via Digiseller / GGsel
order chats.

**Do not change bot code yet** — implement Store-side APIs first; wire the bot
when ready using this guide.

## Roles

| System | Responsibility |
|--------|----------------|
| Bot CRM | Segment Remnawave (`expiring_soon`, etc.), deliver Telegram to local users with `tg_id` |
| Store | Match leftover panel users to marketplace orders; send text via Digiseller/GGsel debates API |

Store does **not** replace the bot segment engine. It is a **delivery backend**
for marketplace channels only.

## Auth

Config already present on the bot side:

- `store_url` — base URL of this service (e.g. `http://backend-bot:5001`)
- `store_api_token` — must equal Store `api_token` in `backend.yml`

All internal CRM endpoints require:

```http
Authorization: Bearer <store_api_token>
```

## Endpoints

Base path: `{store_url}/store/internal/crm`

### POST `/resolve`

Preview how many leftover recipients Store can deliver to.

```json
{
  "remnawave_user_ids": [101, 102],
  "usernames": ["gg_id123", "dig_id456"],
  "emails": ["buyer@example.com"]
}
```

Response:

```json
{
  "count": 2,
  "recipients": [
    {
      "order_id": 10,
      "marketplace": "ggsel",
      "external_order_id": "123",
      "chat_id": "123",
      "remnawave_user_id": 101,
      "remnawave_username": "gg_id123",
      "email": "buyer@example.com",
      "customer_id": 1
    }
  ]
}
```

### POST `/broadcast`

Resolve + send (or dry-run).

```json
{
  "remnawave_user_ids": [101],
  "usernames": [],
  "emails": [],
  "text": "Ваша подписка скоро истечёт. Продлите на GGsel/Digiseller.",
  "dry_run": false
}
```

Response:

```json
{
  "matched": 2,
  "delivered": 2,
  "failed": 0,
  "skipped": 0,
  "details": []
}
```

### GET `/customers/by-email/{email}`

Customer 360 (orders for that email). Useful for support tooling.

## Suggested bot wiring (future)

1. After CRM segment evaluation, split recipients:
   - **Y** — local `users` with `tg_id` → existing Telegram `send_message` action
   - **X−Y** — Remnawave numeric ids/usernames not in local TG set → Store broadcast
2. Preferred hook: `crm-worker` post-step after TG delivery (same pattern as
   dashboard httpx proxy in `routers/store.py` / Telemt).
3. Always call `/resolve` in campaign **preview** so operators see Store coverage.
4. Use `dry_run: true` in preview/launch confirmation.

### Pseudocode

```python
async def deliver_leftover_to_store(user_ids: list[int], text: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{store_url}/store/internal/crm/broadcast",
            headers={"Authorization": f"Bearer {store_api_token}"},
            json={"remnawave_user_ids": user_ids, "text": text, "dry_run": False},
        )
        r.raise_for_status()
        return r.json()
```

## Matching rules on Store

Recipients are matched against local `orders` / `customers` by:

1. `orders.remnawave_user_id` (Remnawave 3 numeric user id)
2. `orders.remnawave_username` (`gg_id*`, `dig_id*`)
3. `customers.email_normalized`

`remnawave_uuids` remains accepted temporarily for historical Remnawave <=2
records, but new integrations must send `remnawave_user_ids`.

Delivery uses the **newest** order chat per customer (`chat_id` /
`external_order_id`).

Users who only exist in Remnawave and never bought via Digiseller/GGsel are
`skipped`.

## Username conventions

| Marketplace | Remnawave username |
|-------------|-------------------|
| GGsel | `gg_id{content_id}` |
| Digiseller | `dig_id{invoice_id}` |

Keep these stable so historical panel users remain resolvable.
