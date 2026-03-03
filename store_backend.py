import logging

import asyncio

import store.api.aio_ggsel as aio_gg

from fastapi import Request, Response, HTTPException
from store.api.digiseller import payment_async_logic
from store.settings import run_webserver, app_uvi
from store.notify import webhook_tg_notify

@app_uvi.post("/digiseller_webhook")
async def payment_webhook(request: Request, response: Response):
    try:
        payment_data = await request.json()
        link = await payment_async_logic(payment_data)
        content = {
                "id": f"{payment_data['id']}",
                "inv": f"{payment_data['inv']}",
                "goods": f"{link}",
                "error": ""
        }
        response.status_code = 200
        return content
    except Exception as e:
        logging.error(f"Ошибка обработки платежа: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "id": "",
                "inv": "0",
                "goods": "",
                "error": "Internal server error"
            }
        )

@app_uvi.post("/ggsel_webhook_new")
async def payment_webhook(request: Request, response: Response):
    try:
        payment_data = await request.json()
        print(payment_data)
        status = await webhook_tg_notify(payment_data, "GGSELL")
        return status
    except Exception as e:
        logging.error(f"Ошибка обработки платежа: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "id": "",
                "inv": "0",
                "goods": "",
                "error": "Internal server error"
            }
        )

async def on_startup():
    """Действия при запуске бота"""
    asyncio.create_task(run_webserver())  # Запуск Uvicorn в фоне
    asyncio.create_task(aio_gg.order_delivery_loop())

async def main():
    await asyncio.gather(
        run_webserver(),
        aio_gg.order_delivery_loop(),
    )

if __name__ == "__main__":
    asyncio.run(main())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
