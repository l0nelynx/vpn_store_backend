from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import store.database.requests as rq
from store.api.auth import verify_api_token
from store.services.messaging import broadcast_to_recipients

crm_router = APIRouter(
    prefix="/store/internal/crm",
    tags=["internal-crm"],
    dependencies=[Depends(verify_api_token)],
)


class ResolveBody(BaseModel):
    remnawave_user_ids: list[int] = Field(default_factory=list)
    # Compatibility for callers that have not migrated from Remnawave <=2 yet.
    remnawave_uuids: list[str] = Field(default_factory=list)
    usernames: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)


class BroadcastBody(ResolveBody):
    text: str
    dry_run: bool = False


@crm_router.post("/resolve")
async def resolve(body: ResolveBody):
    recipients = await rq.resolve_recipients(
        remnawave_user_ids=body.remnawave_user_ids or None,
        remnawave_uuids=body.remnawave_uuids or None,
        usernames=body.usernames or None,
        emails=body.emails or None,
    )
    return {"count": len(recipients), "recipients": recipients}


@crm_router.post("/broadcast")
async def broadcast(body: BroadcastBody):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text required")
    recipients = await rq.resolve_recipients(
        remnawave_user_ids=body.remnawave_user_ids or None,
        remnawave_uuids=body.remnawave_uuids or None,
        usernames=body.usernames or None,
        emails=body.emails or None,
    )
    result = await broadcast_to_recipients(recipients, body.text, dry_run=body.dry_run)
    return {"matched": len(recipients), **result}


@crm_router.get("/customers/by-email/{email}")
async def customer_by_email(email: str):
    data = await rq.get_customer_360(email=email)
    if not data:
        raise HTTPException(status_code=404, detail="Customer not found")
    return data
