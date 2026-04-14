from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import store.database.requests as rq
from store.settings import secrets

_bearer_scheme = HTTPBearer()


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme)):
    if credentials.credentials != secrets.get("api_token"):
        raise HTTPException(status_code=401, detail="Invalid token")
    return credentials


order_params_router = APIRouter(
    prefix="/store/api/order-params",
    tags=["order-params"],
    dependencies=[Depends(verify_token)],
)


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


@order_params_router.get("/")
async def get_order_params(item_id: int | None = None):
    return await rq.get_all_order_params(item_id=item_id)


@order_params_router.post("/", status_code=201)
async def create_order_param(body: OrderParamCreate):
    await rq.create_order_param(
        item_id=body.item_id,
        param_id=body.param_id,
        user_data_id=body.user_data_id,
        type_=body.type,
        data=body.data,
    )
    return {"status": "created"}


@order_params_router.put("/{record_id}")
async def update_order_param(record_id: int, body: OrderParamUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "type" in fields:
        fields["type"] = fields.pop("type")
    updated = await rq.update_order_param(record_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="OrderParam not found")
    return {"status": "updated"}


@order_params_router.delete("/{record_id}")
async def delete_order_param(record_id: int):
    deleted = await rq.delete_order_param(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="OrderParam not found")
    return {"status": "deleted"}
