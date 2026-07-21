# GGsel product options sync

## What works today

**GGsel** option names are synced via **Seller API v2**:

- `Authorization: <ggsel_api_key>` (key from seller.ggsel.com admin)
- `GET {ggsel_base_url}/api_sellers/v2/offers/{offer_id}/options`

`offer_id` is taken from catalog `products.external_item_id` (seller-goods `id_goods`).

Fields: `title_ru` / `title_en`, variant `id` → Store `user_data_id`.

**Digiseller** (separate) still uses Digiseller v1:

- `?token=` from Digiseller apilogin
- `GET {dig_url}/api/products/options/list/{product_id}`

## Why not `/api/products/options` on seller.ggsel.com

That path returns `{"error":"Authentication required"}` and is a **different** auth
gate than Seller API v2 (`UNAUTHORIZED`). GGsel seller API key / apilogin token
do not unlock it. Do not use it for sync.

## Delivery (unchanged)

Fulfillment uses `/api_sellers/api/*?token=` after apilogin — that layer is fine
and unrelated to options sync.

## Future notes (v2 already in use for sync)

See also offer/option schemas:

- https://seller.ggsel.com/docs/en/v2/view-option
- https://seller.ggsel.com/docs/en/v2/schemas/option-list-object
