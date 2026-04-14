# Order Params API

API for managing order parameter mappings (`OrderParam`) in the database.

Base path: `/store/api/order-params`

## Authorization

All endpoints require Bearer token authentication. The token is configured in `backend.yml` as `api_token`.

**Header:**
```
Authorization: Bearer <api_token>
```

Requests without a valid token receive `401 Unauthorized`.

---

## Data Model

Each record maps a combination of `(item_id, param_id, user_data_id)` to a typed value:

| Field          | Type   | Description                                                        |
|----------------|--------|--------------------------------------------------------------------|
| `id`           | int    | Auto-increment primary key                                         |
| `item_id`      | int    | Product ID from the store (GGSel `item_id`)                       |
| `param_id`     | int    | Option ID from the order's `options[].id`                          |
| `user_data_id` | int    | Variant ID from the order's `options[].user_data_id`               |
| `type`         | string | Parameter type: `days`, `hwid`, `location`, `internal_sq`, `external_sq` |
| `data`         | string | Parameter value (days count, device limit, squad UUID, etc.)       |

### Type values

| Type          | Description                              | Example `data`                         |
|---------------|------------------------------------------|----------------------------------------|
| `days`        | Subscription duration in days            | `"30"`, `"90"`, `"180"`, `"360"`       |
| `hwid`        | Device limit (0 = unlimited)             | `"5"`, `"0"`                           |
| `location`    | Squad UUID (used as `template`)          | `"1d371a32-e0d3-45f8-bbc0-cba60f61eeb4"` |
| `internal_sq` | Internal squad UUID (reserved)           | -                                      |
| `external_sq` | External squad UUID (used as `outer_squad`) | `"547e1588-2d00-4281-94e8-c9cfecfb7645"` |

---

## Endpoints

### GET /store/api/order-params/

Get all order parameters. Optionally filter by `item_id`.

**Query parameters:**

| Parameter | Type | Required | Description                  |
|-----------|------|----------|------------------------------|
| `item_id` | int  | No       | Filter results by product ID |

**Request:**
```
GET /store/api/order-params/
GET /store/api/order-params/?item_id=12345
```

**Response** `200 OK`:
```json
[
  {
    "id": 1,
    "item_id": 12345,
    "param_id": 35060,
    "user_data_id": 161578,
    "type": "days",
    "data": "30"
  },
  {
    "id": 2,
    "item_id": 12345,
    "param_id": 35060,
    "user_data_id": 161578,
    "type": "hwid",
    "data": "5"
  }
]
```

---

### POST /store/api/order-params/

Create a new order parameter record.

**Request body:**

| Field          | Type   | Required | Description          |
|----------------|--------|----------|----------------------|
| `item_id`      | int    | Yes      | Product ID           |
| `param_id`     | int    | Yes      | Option ID            |
| `user_data_id` | int    | Yes      | Variant ID           |
| `type`         | string | Yes      | Parameter type       |
| `data`         | string | Yes      | Parameter value      |

**Request:**
```
POST /store/api/order-params/
Content-Type: application/json

{
  "item_id": 12345,
  "param_id": 35060,
  "user_data_id": 161578,
  "type": "days",
  "data": "30"
}
```

**Response** `201 Created`:
```json
{
  "status": "created"
}
```

---

### PUT /store/api/order-params/{id}

Update an existing order parameter by its `id`. Only provided fields will be updated.

**Path parameters:**

| Parameter | Type | Description       |
|-----------|------|-------------------|
| `id`      | int  | Record primary key |

**Request body** (all fields optional, at least one required):

| Field          | Type   | Description          |
|----------------|--------|----------------------|
| `item_id`      | int    | Product ID           |
| `param_id`     | int    | Option ID            |
| `user_data_id` | int    | Variant ID           |
| `type`         | string | Parameter type       |
| `data`         | string | Parameter value      |

**Request:**
```
PUT /store/api/order-params/1
Content-Type: application/json

{
  "data": "90"
}
```

**Response** `200 OK`:
```json
{
  "status": "updated"
}
```

**Response** `404 Not Found`:
```json
{
  "detail": "OrderParam not found"
}
```

---

### DELETE /store/api/order-params/{id}

Delete an order parameter by its `id`.

**Path parameters:**

| Parameter | Type | Description       |
|-----------|------|-------------------|
| `id`      | int  | Record primary key |

**Request:**
```
DELETE /store/api/order-params/1
```

**Response** `200 OK`:
```json
{
  "status": "deleted"
}
```

**Response** `404 Not Found`:
```json
{
  "detail": "OrderParam not found"
}
```

---

## Usage Example

Setting up parameters for a product with `item_id=12345` that has a tariff option (`param_id=35060`) and a location option (`param_id=711004`):

```bash
TOKEN="your_api_token_here"

# Tariff: 1 month, 30 days, hwid limit 5
curl -X POST /store/api/order-params/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"item_id": 12345, "param_id": 35060, "user_data_id": 161578, "type": "days", "data": "30"}'

curl -X POST /store/api/order-params/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"item_id": 12345, "param_id": 35060, "user_data_id": 161578, "type": "hwid", "data": "5"}'

# Location: France squad UUID
curl -X POST /store/api/order-params/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"item_id": 12345, "param_id": 711004, "user_data_id": 1708798, "type": "location", "data": "1d371a32-e0d3-45f8-bbc0-cba60f61eeb4"}'

# Verify
curl -H "Authorization: Bearer $TOKEN" /store/api/order-params/?item_id=12345
```
