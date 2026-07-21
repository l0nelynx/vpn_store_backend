from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from store.api.auth import verify_admin
from store.services import messaging
import store.database.requests as rq

messages_router = APIRouter(
    prefix="/store/api/messages",
    tags=["messages"],
    dependencies=[Depends(verify_admin)],
)


class SendBody(BaseModel):
    text: str


@messages_router.get("/inbox")
async def inbox(limit: int = 50, offset: int = 0):
    return await rq.list_inbox_threads(limit=limit, offset=offset)


@messages_router.get("/customer/{customer_id}")
async def customer_messages(customer_id: int):
    await messaging.sync_customer_messages(customer_id)
    return await rq.list_messages(customer_id=customer_id)


@messages_router.get("/order/{order_id}")
async def order_messages(order_id: int):
    await messaging.sync_order_messages(order_id)
    return await rq.list_messages(order_id=order_id)


@messages_router.post("/order/{order_id}/send")
async def send_order_message(order_id: int, body: SendBody):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text required")
    result = await messaging.send_to_order(order_id, body.text)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


@messages_router.post("/order/{order_id}/sync")
async def sync_order(order_id: int):
    count = await messaging.sync_order_messages(order_id)
    return {"synced": count}
