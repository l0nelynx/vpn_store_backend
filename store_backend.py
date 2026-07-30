import asyncio
import json
import logging
from urllib.parse import parse_qs

from fastapi import Request, Response, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from store.domain.pipeline import PipelineError
from store.services.runtime import handle_digiseller_supplier
from store.api.order_params_router import order_params_router
from store.api.admin_router import admin_router
from store.api.crm_router import crm_router
from store.api.messages_router import messages_router
from store.api.v1_router import router as v1_router
from store.settings import run_webserver, app_uvi
from store.notify import webhook_tg_notify

app_uvi.include_router(order_params_router)
app_uvi.include_router(admin_router)
app_uvi.include_router(crm_router)
app_uvi.include_router(messages_router)
app_uvi.include_router(v1_router)


@app_uvi.get("/store/health", tags=["health"])
async def health():
    from sqlalchemy import text
    from store.database.models import async_session

    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    return {"ok": True, "database": "postgresql", "runtime": "api"}

_admin_dist = Path(__file__).parent / "admin" / "dist"
if _admin_dist.is_dir():
    _assets = _admin_dist / "assets"
    if _assets.is_dir():
        app_uvi.mount(
            "/store/admin/assets",
            StaticFiles(directory=str(_assets)),
            name="admin-assets",
        )

    @app_uvi.get("/store/admin")
    @app_uvi.get("/store/admin/")
    @app_uvi.get("/store/admin/{full_path:path}")
    async def admin_spa(full_path: str = ""):
        """SPA fallback so /store/admin/parameters etc. serve index.html."""
        if full_path:
            candidate = _admin_dist / full_path
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(_admin_dist / "index.html")

@app_uvi.post("/store/digiseller_webhook")
async def payment_webhook(request: Request, response: Response):
    try:
        content_type = request.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            payment_data = await request.json()
        else:
            form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
            payment_data = {key: values[-1] for key, values in form.items()}
            if isinstance(payment_data.get("options"), str):
                try:
                    payment_data["options"] = json.loads(payment_data["options"])
                except ValueError:
                    payment_data["options"] = []
        content = await handle_digiseller_supplier(payment_data)
        response.status_code = 200
        return content
    except PipelineError as e:
        if e.code == "invalid_signature":
            raise HTTPException(status_code=403, detail="invalid signature") from e
        logging.error("Digiseller pipeline error: %s", e)
        return {"id": "", "inv": ""}
    except HTTPException:
        raise
    except Exception as e:
        logging.error("Ошибка обработки платежа: %s", e)
        # A temporary internal failure must remain opaque to the buyer. Returning
        # only id/inv asks Digiseller Supplier API to retry the same delivery.
        return {
            "id": str(payment_data.get("id") or "") if isinstance(payment_data, dict) else "",
            "inv": str(payment_data.get("inv") or "") if isinstance(payment_data, dict) else "",
        }


@app_uvi.post("/store/ggsel_webhook_new")
async def ggsel_payment_webhook(request: Request, response: Response):
    try:
        payment_data = await request.json()
        logging.debug("GGsel webhook data: %s", payment_data)
        await webhook_tg_notify(payment_data, "GGSELL")
        # V1 does not define this payload as a trusted fulfillment trigger.
        # Keep the endpoint for existing senders, but actual delivery starts
        # only after seller-last-sales + purchase/info verification in worker.
        response.status_code = 202
        return {"notify": 200, "fulfill": "verification_queued"}
    except Exception as e:
        logging.error("Ошибка обработки платежа: %s", e)
        raise HTTPException(
            status_code=500,
            detail={
                "id": "",
                "inv": "0",
                "goods": "",
                "error": "Internal server error",
            },
        )


async def main():
    from store.database.models import async_main as db_init

    await db_init()

    await run_webserver()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(main())
