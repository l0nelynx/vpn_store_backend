import aiohttp
import asyncio
import logging
import time
import hashlib

from store.settings import secrets
import store.database.requests as rq
from store.notify import send_tg_alert as send_alert
from store.services.fulfillment import fulfill_order, mark_delivered, parse_order_params

logger = logging.getLogger(__name__)


def _build_purchase_message(sub_link: str) -> str:
    return (
        f"Спасибо за покупку!\n"
        f"Ваша ссылка для подписки : {sub_link} \n\n"
        f"Просто добавьте ее в v2ray-клиент (например Happ) \n"
        f"Либо вы можете открыть ее в браузере, чтобы получить подробные \n"
        f"инструкции с ссылками на скачивание поддерживаемых клиентов. \n"
        f"Если у вас возникнут какие-либо проблемы, пишите в этот чат, \n"
        f"также вы можете найти наш тг-бот @{secrets.get('tg_bot_username')} - \n"
        f"там вы можете найти инструкции, чат поддержки, а также получить \n"
        f"возможность управлять подпиской в тг (для этого обратитесь в чат поддержки и сообщите номер заказа)\n"
    )


async def get_token(session: aiohttp.ClientSession) -> str:
    timestamp = time.time()
    sign = secrets.get("ggsel_api_key") + str(timestamp)
    sign = hashlib.sha256(sign.encode("utf-8")).hexdigest()
    payload = {
        "seller_id": secrets.get("ggsel_seller_id"),
        "timestamp": timestamp,
        "sign": sign,
    }
    headers = {"Accept": "application/json"}
    async with session.post(
        "/api_sellers/api/apilogin",
        json=payload,
        headers=headers,
    ) as response:
        data = await response.json()
        return data["token"]


async def send_message(
    session: aiohttp.ClientSession,
    id_i: int,
    message: str,
    token: str,
) -> int:
    retries = secrets.get("ggsel_request_retries") or 3
    for attempt in range(retries + 1):
        payload = {"message": message}
        async with session.post(
            f"/api_sellers/api/debates/v2?token={token}&id_i={id_i}",
            json=payload,
        ) as response:
            status = response.status
            data = await response.read()
            if status == 200:
                await send_alert(
                    f"Товар успешно отправлен\n"
                    f"Содержимое ответа:[{status}]{data.decode('utf-8')}\n"
                    f"<b><a href='https://seller.ggsel.net/messages"
                    f"?chatId={id_i}'>Чат</a></b>",
                    "GGSELL",
                )
                return 200
            logger.error("Send message failed: %s", data.decode("utf-8"))
            await send_alert(
                f"Ошибка отправки товара:\n"
                f"[{status}]:{data.decode('utf-8')}\n"
                f"Попытка: {attempt + 1}/{retries + 1}\n"
                f"Повтор через {secrets.get('ggsel_retry_timeout')} секунд",
                "GGSELL",
            )
            if attempt < retries:
                await asyncio.sleep(secrets.get("ggsel_retry_timeout") or 5)
    return 400


async def return_last_sales(
    session: aiohttp.ClientSession,
    top: int = 3,
    token: str = None,
) -> dict:
    headers = {"Accept": "application/json", "locale": "ru-RU"}
    seller_id = secrets.get("ggsel_seller_id")
    async with session.get(
        f"/api_sellers/api/seller-last-sales?token={token}&seller_id={seller_id}&top={top}",
        headers=headers,
    ) as response:
        return await response.json()


async def get_order_info(
    session: aiohttp.ClientSession,
    inv_id: int,
    token: str,
) -> dict:
    headers = {"Accept": "application/json", "locale": "ru-RU"}
    async with session.get(
        f"/api_sellers/api/purchase/info/{inv_id}?token={token}",
        headers=headers,
    ) as response:
        return await response.json()


async def list_seller_goods(session: aiohttp.ClientSession, token: str) -> dict:
    headers = {"Accept": "application/json", "locale": "ru-RU"}
    payload = {
        "seller_id": secrets.get("ggsel_seller_id"),
        "page": 1,
        "rows": 1000,
        "show_hidden": 1,
    }
    async with session.post(
        f"/api_sellers/api/seller-goods?token={token}",
        json=payload,
        headers=headers,
    ) as response:
        return await response.json()


def _ggsel_options_base_url() -> str:
    """GGsel seller host: /api/products/options/... (v1)."""
    return (
        secrets.get("ggsel_options_url")
        or secrets.get("ggsel_base_url")
        or "https://seller.ggsel.com"
    ).rstrip("/")


async def list_product_options(
    session: aiohttp.ClientSession, token: str, product_id: int
) -> list[dict]:
    from store.api.options_v1 import list_product_options as _list

    return await _list(
        session, base_url=_ggsel_options_base_url(), token=token, product_id=product_id
    )


async def get_product_option(
    session: aiohttp.ClientSession, token: str, option_id: int
) -> dict | None:
    from store.api.options_v1 import get_product_option as _get

    return await _get(
        session, base_url=_ggsel_options_base_url(), token=token, option_id=option_id
    )


async def list_chats(session: aiohttp.ClientSession, token: str) -> dict:
    async with session.get(
        f"/api_sellers/api/debates/v2/chats?token={token}",
    ) as response:
        return await response.json()


async def list_messages(
    session: aiohttp.ClientSession,
    token: str,
    id_i: int,
    count: int = 50,
) -> list:
    async with session.get(
        f"/api_sellers/api/debates/v2?token={token}&id_i={id_i}&count={count}",
    ) as response:
        if response.status != 200:
            return []
        data = await response.json()
        if isinstance(data, list):
            return data
        return data.get("items") or data.get("messages") or []


async def fulfill_ggsel_order(
    order_info: dict,
    session: aiohttp.ClientSession,
    token: str,
    db_session=None,
) -> dict | None:
    content = order_info.get("content") or order_info
    content_id = content.get("content_id") or content.get("id_i")
    if content_id is None:
        return None
    invoice_state = content.get("invoice_state")
    if invoice_state is not None and not (3 <= int(invoice_state) <= 4):
        logger.info("GGsel order %s not paid (state=%s)", content_id, invoice_state)
        return None

    options = content.get("options") or []
    item_id = content.get("item_id")
    buyer = content.get("buyer_info") or {}
    email = buyer.get("email")
    invoice_id = content.get("invoice_id") or content.get("inv")

    order_params = await parse_order_params(
        item_id=item_id,
        options=options,
        id_key="id",
        data_key="user_data_id",
        session=db_session,
    )
    days = order_params["days"] if order_params["days"] is not None else 30

    result = await fulfill_order(
        marketplace="ggsel",
        external_order_id=str(content_id),
        remnawave_username=f"gg_id{content_id}",
        days=days,
        email=email,
        invoice_id=str(invoice_id) if invoice_id else None,
        item_id=item_id,
        options=options,
        chat_id=str(content_id),
        template=order_params["template"],
        hwid=order_params["hwid"],
        outer_squad=order_params["outer_squad"],
        ggsel_buyer_id=str(buyer.get("buyer_id") or content_id),
        session=db_session,
    )
    if not result.get("sub"):
        return result

    # Never spam: only notify buyer on brand-new provision (or explicit resend).
    if not result.get("should_notify_buyer"):
        logger.info(
            "Skip buyer message for %s event=%s",
            content_id,
            result.get("event"),
        )
        return result

    delivery_status = await send_message(
        session,
        id_i=int(content_id),
        message=_build_purchase_message(result["sub"]),
        token=token,
    )
    if delivery_status == 200:
        await mark_delivered(result["order_id"], session=db_session)
    return result


async def check_new_orders(
    session: aiohttp.ClientSession,
    top: int = 3,
    token: str = None,
) -> None:
    last_sales = await return_last_sales(session, top=top, token=token)
    for sale in last_sales.get("sales") or []:
        order_info = await get_order_info(session, sale["invoice_id"], token=token)
        async with rq.get_session() as db_session:
            await fulfill_ggsel_order(order_info, session, token, db_session=db_session)
            await db_session.commit()


async def process_webhook_payload(payment_data: dict) -> dict:
    """Fulfill from GGsel webhook when payload contains order identifiers."""
    content = payment_data.get("content") or payment_data
    invoice_id = (
        content.get("invoice_id")
        or payment_data.get("invoice_id")
        or payment_data.get("inv")
    )
    content_id = content.get("content_id") or payment_data.get("content_id")

    base = secrets.get("ggsel_base_url") or "https://seller.ggsel.com"
    async with aiohttp.ClientSession(base_url=base) as http:
        token = await get_token(http)
        if invoice_id:
            order_info = await get_order_info(http, int(invoice_id), token)
        elif content_id:
            # Minimal synthetic info from webhook body
            order_info = {"content": content}
        else:
            return {"status": "ignored", "reason": "no invoice/content id"}
        async with rq.get_session() as db_session:
            result = await fulfill_ggsel_order(
                order_info, http, token, db_session=db_session
            )
            await db_session.commit()
            return {"status": "ok", "result": result}


async def order_delivery_loop() -> None:
    base = secrets.get("ggsel_base_url") or "https://seller.ggsel.com"
    async with aiohttp.ClientSession(base_url=base) as session:
        error_counter = 0
        while True:
            try:
                token = await get_token(session)
                await check_new_orders(
                    session,
                    top=secrets.get("ggsel_top_value") or 10,
                    token=token,
                )
                error_counter = 0
            except Exception as e:
                error_counter += 1
                logger.error("Ошибка при проверке новых заказов: %s", e)
                threshold = secrets.get("ggsel_error_threshold") or 5
                if error_counter > threshold:
                    await send_alert(
                        f"Ошибка при проверке новых заказов: {e}\n"
                        f" Неудачных запросов подряд: {error_counter}",
                        "GGSELL",
                    )
            await asyncio.sleep((secrets.get("ggsel_check_interval") or 1) * 60)
