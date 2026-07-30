from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import store.database.requests as rq
from store.api.auth import (
    check_admin_password,
    create_session,
    revoke_refresh,
    rotate_refresh,
    verify_admin,
)
from store.services.catalog_sync import sync_all_catalogs
from store.services.option_sync import sync_product_options
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


class ParamMappingCreate(BaseModel):
    type: str
    label: str
    value: str


class ParamMappingUpdate(BaseModel):
    type: str | None = None
    label: str | None = None
    value: str | None = None


@admin_router.post("/login")
async def login(body: LoginBody, response: Response):
    if not check_admin_password(body.username.strip(), body.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    result = await create_session(body.username.strip())
    response.set_cookie(
        "store_refresh", result.pop("refresh_token"), httponly=True,
        secure=bool(secrets.get("admin_cookie_secure", True)), samesite="strict",
        max_age=int(secrets.get("admin_refresh_ttl") or 30 * 24 * 3600), path="/store/api/admin",
    )
    return {
        "token": result["access_token"],
        "access_token": result["access_token"],
        "token_type": "bearer",
        "expires_in": result["expires_in"],
        "username": result["username"],
    }


@admin_router.post("/session")
async def login_session(body: LoginBody, response: Response):
    """Preferred browser login: rotating refresh token stays in an HttpOnly cookie."""
    if not check_admin_password(body.username.strip(), body.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    result = await create_session(body.username.strip())
    response.set_cookie(
        "store_refresh", result.pop("refresh_token"), httponly=True,
        secure=bool(secrets.get("admin_cookie_secure", True)), samesite="strict",
        max_age=int(secrets.get("admin_refresh_ttl") or 30 * 24 * 3600), path="/store/api/admin",
    )
    return {
        "token": result["access_token"],
        "token_type": "bearer",
        "expires_in": result["expires_in"],
        "username": result["username"],
    }


@admin_router.post("/refresh")
async def refresh_session(request: Request, response: Response):
    token = request.cookies.get("store_refresh")
    if not token:
        raise HTTPException(status_code=401, detail="Refresh cookie missing")
    result = await rotate_refresh(token)
    response.set_cookie(
        "store_refresh", result.pop("refresh_token"), httponly=True,
        secure=bool(secrets.get("admin_cookie_secure", True)), samesite="strict",
        max_age=int(secrets.get("admin_refresh_ttl") or 30 * 24 * 3600), path="/store/api/admin",
    )
    return {"token": result["access_token"], "token_type": "bearer", "expires_in": result["expires_in"]}


@admin_router.post("/logout", dependencies=[Depends(verify_admin)])
async def logout(request: Request, response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    await revoke_refresh(request.cookies.get("store_refresh"))
    response.delete_cookie("store_refresh", path="/store/api/admin")
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
    q: str | None = None,
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    items = await rq.list_orders(
        email=email,
        marketplace=marketplace,
        remnawave_uuid=remnawave_uuid,
        remnawave_username=remnawave_username,
        external_order_id=external_order_id,
        q=q,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    total = await rq.count_orders(
        email=email,
        marketplace=marketplace,
        remnawave_uuid=remnawave_uuid,
        remnawave_username=remnawave_username,
        external_order_id=external_order_id,
        q=q,
    )
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


@admin_router.delete("/order-params/variant", dependencies=[Depends(verify_admin)])
async def admin_delete_order_param_variant(
    item_id: int,
    param_id: int,
    user_data_id: int,
    marketplace: str | None = None,
):
    """Delete all mapped values for a variant and drop its cached label."""
    params_deleted = await rq.delete_order_params_for_variant(
        item_id=item_id, param_id=param_id, user_data_id=user_data_id
    )
    labels_deleted = await rq.delete_product_option_labels_for_variant(
        item_id=item_id,
        param_id=param_id,
        user_data_id=user_data_id,
        marketplace=marketplace,
    )
    if params_deleted == 0 and labels_deleted == 0:
        raise HTTPException(status_code=404, detail="Variant not found")
    return {
        "status": "deleted",
        "order_params": params_deleted,
        "labels": labels_deleted,
    }


@admin_router.delete("/order-params/{record_id}", dependencies=[Depends(verify_admin)])
async def admin_delete_order_param(record_id: int):
    deleted = await rq.delete_order_param(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="OrderParam not found")
    return {"status": "deleted"}


# ── Param value mappings (label catalog for Parameters dropdown) ────────────


@admin_router.get("/param-mappings", dependencies=[Depends(verify_admin)])
async def admin_list_param_mappings(type: str | None = None):
    return await rq.list_param_value_mappings(type_=type)


@admin_router.post("/param-mappings", status_code=201, dependencies=[Depends(verify_admin)])
async def admin_create_param_mapping(body: ParamMappingCreate):
    try:
        return await rq.create_param_value_mapping(
            type_=body.type.strip(),
            label=body.label.strip(),
            value=body.value.strip(),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@admin_router.put("/param-mappings/{record_id}", dependencies=[Depends(verify_admin)])
async def admin_update_param_mapping(record_id: int, body: ParamMappingUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "type" in fields and fields["type"] is not None:
        fields["type"] = fields["type"].strip()
    if "label" in fields and fields["label"] is not None:
        fields["label"] = fields["label"].strip()
    if "value" in fields and fields["value"] is not None:
        fields["value"] = fields["value"].strip()
    updated = await rq.update_param_value_mapping(record_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return updated


@admin_router.delete("/param-mappings/{record_id}", dependencies=[Depends(verify_admin)])
async def admin_delete_param_mapping(record_id: int):
    deleted = await rq.delete_param_value_mapping(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"status": "deleted"}


# ── Product option labels (names from marketplace API v1) ───────────────────


@admin_router.post("/sync-product-options", dependencies=[Depends(verify_admin)])
async def admin_sync_product_options(
    marketplace: str | None = None,
    item_id: int | None = None,
):
    return await sync_product_options(marketplace=marketplace, item_id=item_id)


@admin_router.get("/product-option-labels", dependencies=[Depends(verify_admin)])
async def admin_list_product_option_labels(
    marketplace: str | None = None,
    item_id: int | None = None,
):
    return await rq.list_product_option_labels(marketplace=marketplace, item_id=item_id)
