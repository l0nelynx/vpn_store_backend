from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import store.database.requests as rq
from store.api.auth import (
    check_admin_password,
    create_session_token,
    revoke_session_token,
    verify_admin,
)
from store.services.catalog_sync import sync_all_catalogs
from store.services.order_sync import sync_all_orders
from store.settings import secrets

admin_router = APIRouter(
    prefix="/store/api/admin",
    tags=["admin"],
)

_bearer = HTTPBearer(auto_error=False)


class LoginBody(BaseModel):
    username: str = "admin"
    password: str


class OrderParamCreate(BaseModel):
    item_id: int
    param_id: int
    user_data_id: int
    type: str
    data: str


class OrderParamUpdate(BaseModel):
    item_id: int | None = None
    param_id: int | None = None
    user_data_id: int | None = None
    type: str | None = None
    data: str | None = None


@admin_router.post("/login")
async def login(body: LoginBody):
    if not check_admin_password(body.username.strip(), body.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_session_token(username=body.username.strip())
    return {
        "token": token,
        "token_type": "bearer",
        "expires_in": int(secrets.get("admin_session_ttl") or 12 * 3600),
        "username": body.username.strip(),
    }


@admin_router.post("/logout", dependencies=[Depends(verify_admin)])
async def logout(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if credentials:
        revoke_session_token(credentials.credentials)
    return {"ok": True}


@admin_router.get("/me", dependencies=[Depends(verify_admin)])
async def me(auth=Depends(verify_admin)):
    return {"ok": True, "auth": auth}


@admin_router.post("/sync-catalog", dependencies=[Depends(verify_admin)])
async def sync_catalog():
    return await sync_all_catalogs()


@admin_router.post("/sync-orders", dependencies=[Depends(verify_admin)])
async def sync_orders(top: int = Query(50, ge=1, le=200)):
    """Pull recent GGsel (+ Digiseller if configured) sales into DB without buyer spam."""
    return await sync_all_orders(top=top)


@admin_router.get("/products", dependencies=[Depends(verify_admin)])
async def products(marketplace: str | None = Query(None)):
    return await rq.list_products(marketplace=marketplace)


@admin_router.get("/orders", dependencies=[Depends(verify_admin)])
async def orders(
    email: str | None = None,
    marketplace: str | None = None,
    remnawave_uuid: str | None = None,
    remnawave_username: str | None = None,
    external_order_id: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    items = await rq.list_orders(
        email=email,
        marketplace=marketplace,
        remnawave_uuid=remnawave_uuid,
        remnawave_username=remnawave_username,
        external_order_id=external_order_id,
        limit=limit,
        offset=offset,
    )
    total = await rq.count_orders(email=email, marketplace=marketplace)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@admin_router.get("/customers/{customer_id}", dependencies=[Depends(verify_admin)])
async def customer_detail(customer_id: int):
    data = await rq.get_customer_360(customer_id=customer_id)
    if not data:
        raise HTTPException(status_code=404, detail="Customer not found")
    return data


@admin_router.get("/customers", dependencies=[Depends(verify_admin)])
async def customers(email: str | None = None, remnawave_uuid: str | None = None):
    data = await rq.get_customer_360(email=email, remnawave_uuid=remnawave_uuid)
    if not data:
        raise HTTPException(status_code=404, detail="Customer not found")
    return data


# ── Mappings (admin session; bot keeps /store/api/order-params + api_token) ──


@admin_router.get("/order-params", dependencies=[Depends(verify_admin)])
async def admin_list_order_params(item_id: int | None = None):
    return await rq.get_all_order_params(item_id=item_id)


@admin_router.post("/order-params", status_code=201, dependencies=[Depends(verify_admin)])
async def admin_create_order_param(body: OrderParamCreate):
    await rq.create_order_param(
        item_id=body.item_id,
        param_id=body.param_id,
        user_data_id=body.user_data_id,
        type_=body.type,
        data=body.data,
    )
    return {"status": "created"}


@admin_router.put("/order-params/{record_id}", dependencies=[Depends(verify_admin)])
async def admin_update_order_param(record_id: int, body: OrderParamUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await rq.update_order_param(record_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="OrderParam not found")
    return {"status": "updated"}


@admin_router.delete("/order-params/{record_id}", dependencies=[Depends(verify_admin)])
async def admin_delete_order_param(record_id: int):
    deleted = await rq.delete_order_param(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="OrderParam not found")
    return {"status": "deleted"}
