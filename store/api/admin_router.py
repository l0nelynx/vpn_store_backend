from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import store.database.requests as rq
from store.api.auth import verify_admin
from store.services.catalog_sync import sync_all_catalogs
from store.settings import secrets

admin_router = APIRouter(
    prefix="/store/api/admin",
    tags=["admin"],
)


class LoginBody(BaseModel):
    password: str


@admin_router.post("/login")
async def login(body: LoginBody):
    admin_pw = secrets.get("admin_password") or secrets.get("dashboard_password") or secrets.get("api_token")
    if not admin_pw or body.password != admin_pw:
        raise HTTPException(status_code=401, detail="Invalid password")
    return {"token": admin_pw, "token_type": "bearer"}


@admin_router.get("/me", dependencies=[Depends(verify_admin)])
async def me():
    return {"ok": True}


@admin_router.post("/sync-catalog", dependencies=[Depends(verify_admin)])
async def sync_catalog():
    return await sync_all_catalogs()


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
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    return await rq.list_orders(
        email=email,
        marketplace=marketplace,
        remnawave_uuid=remnawave_uuid,
        remnawave_username=remnawave_username,
        external_order_id=external_order_id,
        limit=limit,
        offset=offset,
    )


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
