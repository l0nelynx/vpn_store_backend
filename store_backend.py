import logging

import asyncio
import aiohttp

import store.api.aio_ggsel as aio_gg

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from fastapi import Request, Response, HTTPException
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from store.api.digiseller import payment_async_logic
from store.api.order_params_router import order_params_router
from store.api.admin_router import admin_router
from store.api.crm_router import crm_router
from store.api.messages_router import messages_router
from store.settings import run_webserver, app_uvi, backend_bot, secrets
from store.notify import webhook_tg_notify

app_uvi.include_router(order_params_router)
app_uvi.include_router(admin_router)
app_uvi.include_router(crm_router)
app_uvi.include_router(messages_router)

_admin_dist = Path(__file__).parent / "admin" / "dist"
if _admin_dist.is_dir():
    app_uvi.mount("/store/admin", StaticFiles(directory=str(_admin_dist), html=True), name="admin")

router = Router()


@router.message(Command("message"))
async def cmd_message(message: Message) -> None:
    if message.from_user.id != int(secrets.get("admin_id")):
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Использование: /message <id_i> <текст>")
        return

    try:
        id_i = int(args[1])
    except ValueError:
        await message.reply("id_i должен быть числом")
        return

    text = args[2]

    try:
        async with aiohttp.ClientSession(
            base_url=secrets.get("ggsel_base_url") or "https://seller.ggsel.com"
        ) as session:
            token = await aio_gg.get_token(session)
            status = await aio_gg.send_message(session, id_i, text, token)
        if status == 200:
            await message.reply(f"Сообщение отправлено (id_i={id_i})")
        else:
            await message.reply(f"Ошибка отправки, статус: {status}")
    except Exception as e:
        await message.reply(f"Ошибка: {e}")


@app_uvi.post("/store/digiseller_webhook")
async def payment_webhook(request: Request, response: Response):
    try:
        payment_data = await request.json()
        link = await payment_async_logic(payment_data)
        if link in (400, None):
            raise HTTPException(status_code=400, detail="bad request")
        content = {
            "id": f"{payment_data['id']}",
            "inv": f"{payment_data['inv']}",
            "goods": f"{link}",
            "error": "",
        }
        response.status_code = 200
        return content
    except HTTPException:
        raise
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


@app_uvi.post("/store/ggsel_webhook_new")
async def ggsel_payment_webhook(request: Request, response: Response):
    try:
        payment_data = await request.json()
        logging.debug("GGsel webhook data: %s", payment_data)
        await webhook_tg_notify(payment_data, "GGSELL")
        try:
            result = await aio_gg.process_webhook_payload(payment_data)
            return {"notify": 200, "fulfill": result}
        except Exception as fe:
            logging.error("GGsel webhook fulfill error: %s", fe)
            return {"notify": 200, "fulfill_error": str(fe)}
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

    dp = Dispatcher()
    dp.include_router(router)
    await asyncio.gather(
        run_webserver(),
        aio_gg.order_delivery_loop(),
        dp.start_polling(backend_bot),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(main())
