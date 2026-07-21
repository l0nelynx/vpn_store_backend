# GGsel Seller API v2 — product options (future)

Runtime option sync in Store:

- **GGsel**: on `ggsel_base_url` (`https://seller.ggsel.com`)
  - `GET /api/products/options/list/{product_id}`
  - `GET /api/products/options/{option_id}`
  - Auth: header `Authorization: <ggsel_api_key>` (seller admin API key).
    Query `?token=` from apilogin is **not** accepted here → 401.
- **Digiseller**: on `dig_url` with `?token=` from Digiseller `apilogin`

See `store/api/options_v1.py` and `store/services/option_sync.py`.

This note is for when Digi/GGsel deprecate v1 and we must move to **Seller API v2**.

## Why not v2 today

- v2 options are keyed by **`offer_id`**, not the catalog `item_id` / `id_goods` we store in `products.external_item_id`.
- Field renames break our parsers without a deliberate cutover.
- Order fulfillment still receives GGsel options as `id` + `user_data_id` (v1 naming); that must stay aligned.

## Known v2 deltas (from current GSellers docs)

| v1 (Digiseller-compatible) | v2 (GSellers) |
|----------------------------|---------------|
| Localized `name: [{locale, value}]` | `title_ru` / `title_en` (and comments similarly) |
| Option id → Store `param_id` | Option still has `id` |
| Variant id → Store `user_data_id` | Variant still has `id` (confirm equals order `user_data_id`) |
| Paths under `/api/products/options/...` | `GET /api_sellers/v2/offers/:offer_id/options/:id` |
| — | Variant `status` (`active` / …) is a **lifecycle** flag, **not** `user_data_id` |

Docs references:

- https://seller.ggsel.com/docs/en/v2/view-option
- https://seller.ggsel.com/docs/en/v2/schemas/option-list-object
- https://seller.ggsel.com/docs/en/v2/schemas/option-object

## Cutover checklist

1. Map Store `Product.external_item_id` ↔ v2 `offer_id` (may need a new column or lookup).
2. Rewrite `options_v1` client (or add `options_v2`) for list/detail with `title_ru`/`title_en`.
3. Confirm order webhook/purchase payload still uses the same ids for `param_id` / `user_data_id` (or update `parse_order_params` keys).
4. Re-run option sync; spot-check Parameters UI names vs Remnawave fulfill for a live sale.
5. Keep v1 behind a config flag until dig/ggsel remove it.
