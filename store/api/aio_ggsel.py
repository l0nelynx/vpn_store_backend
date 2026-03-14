import aiohttp
import asyncio
import json
import logging
import time
import hashlib
import uuid

import store.api.marzban.templates as templates
import store.api.remnawave.squads as squads
from store.settings import secrets
from store.api.digiseller import get_variant_info, JSON_PATH
import store.database.requests as rq
from store.notify import send_tg_alert as send_alert
from store.tools import create_subscription_for_order

logger = logging.getLogger(__name__)


def _ggsel_user_id(content_id: int) -> int:
    return int(f"99{content_id}")


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
    sign = secrets.get('ggsel_api_key') + str(timestamp)
    sign = hashlib.sha256(sign.encode("utf-8")).hexdigest()
    payload = {
        "seller_id": secrets.get("ggsel_seller_id"),
        "timestamp": timestamp,
        "sign": sign,
    }
    headers = {
        'Accept': 'application/json',
    }
    async with session.post(
        "/api_sellers/api/apilogin",
        json=payload,
        headers=headers,
    ) as response:
        data = await response.json()
        logger.debug("Token response: %s", data)
        return data['token']


async def send_message(
    session: aiohttp.ClientSession,
    id_i: int,
    message: str,
    token: str,
) -> int:
    success_counter = 0
    while success_counter <= secrets.get('ggsel_request_retries'):
        payload = {
            "message": message,
        }
        async with session.post(
            f"/api_sellers/api/debates/v2?token={token}&id_i={id_i}",
            json=payload,
        ) as response:
            status = response.status
            logger.info("Send goods: %s", status)
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
            else:
                logger.error("Send message failed: %s", data.decode("utf-8"))
                await send_alert(
                    f"Ошибка отправки товара:\n"
                    f"[{status}]:{data.decode('utf-8')}\n"
                    f"Попытка: {success_counter}/"
                    f"{secrets.get('ggsel_request_retries')}\n"
                    f"Повтор через {secrets.get('ggsel_retry_timeout')} секунд",
                    "GGSELL",
                )
                success_counter += 1
                await asyncio.sleep(secrets.get('ggsel_retry_timeout'))
                return 400


async def return_last_sales(
    session: aiohttp.ClientSession,
    top: int = 3,
    token: str = None,
) -> dict:
    headers = {
        'Accept': 'application/json',
        'locale': 'ru-RU',
    }
    seller_id = secrets.get('ggsel_seller_id')
    async with session.get(
        f"/api_sellers/api/seller-last-sales"
        f"?token={token}&seller_id={seller_id}&top={top}",
        headers=headers,
    ) as response:
        status = response.status
        logger.debug("Last sales status: %s", status)
        data = await response.json()
        logger.debug("Last sales data: %s", data)
        return data


async def get_order_info(
    session: aiohttp.ClientSession,
    inv_id: int,
    token: str,
) -> dict:
    headers = {
        'Accept': 'application/json',
        'locale': 'ru-RU',
    }
    async with session.get(
        f"/api_sellers/api/purchase/info/{inv_id}?token={token}",
        headers=headers,
    ) as response:
        data = await response.json()
        logger.debug("Order info: %s", data)
        return data


async def get_order_params(order_info: dict) -> dict:
    index_tax = int(not order_info['content']['options'][0]['name'] == 'Тариф')
    merchant_id = order_info['content']['options'][index_tax]['id']
    tariff_id = order_info['content']['options'][index_tax]['user_data_id']
    logger.debug("Options length: %d", len(order_info['content']['options']))
    location_param_id = order_info['content']['options'][index_tax ^ 1]['id']
    location_id = order_info['content']['options'][index_tax ^ 1]['user_data_id']
    location = get_variant_info(JSON_PATH, location_param_id, location_id, 'name') # Get location name
    client_name = get_variant_info(JSON_PATH, location_param_id, location_id, 'outer_squad')  # Get location name
    days = get_variant_info(JSON_PATH, merchant_id, tariff_id, 'days')
    hwid = get_variant_info(JSON_PATH, merchant_id, tariff_id, 'hwid')
    template = getattr(squads, location, None) if location else None
    outer_squad = getattr(squads, client_name, None) if client_name else None
    logger.debug("Selected template: %s", template)
    return {"days": days, "template": template, "hwid": hwid, "outer_squad": outer_squad}


async def order_register_routine(
    order_info: dict,
    days: int,
    template: str,
    session: aiohttp.ClientSession,
    token: str,
    hwid: int = None,
    outer_squad: str = None,
) -> None:
    content_id = order_info['content']['content_id']
    email = order_info['content']['buyer_info']['email'] # Get buyer email
    user_id = _ggsel_user_id(content_id)
    await send_alert('Найден новый оплаченный заказ, регистрация заказа', "GGSELL")
    await rq.create_transaction(
        user_tg_id=user_id,
        user_transaction=str(uuid.uuid4()),
        username=f"99{content_id}",
        days=days,
    )
    goods = await create_subscription_for_order(content_id, days, template, "gg_id", email, hwid, outer_squad)
    await asyncio.sleep(secrets.get('ggsel_retry_timeout'))
    await send_alert('Подписка сформирована', "GGSELL")
    delivery_status = await send_message(
        session,
        id_i=content_id,
        message=_build_purchase_message(goods["sub"]),
        token=token,
    )
    if delivery_status == 200:
        await rq.update_delivery_status(user_id, 1)


async def order_already_registered_routine(
    order_id_check: dict,
    order_info: dict,
    days: int,
    template: str,
    session: aiohttp.ClientSession,
    token: str,
    hwid: int = None,
    outer_squad: str = None,
) -> None:
    content_id = order_info['content']['content_id']
    email = order_info['content']['buyer_info']['email'] # Get buyer email
    user_id = _ggsel_user_id(content_id)
    if order_id_check['delivery_status'] == 0:
        goods = await create_subscription_for_order(content_id, days, template, "gg_id", email, hwid, outer_squad)
        delivery_status = await send_message(
            session,
            id_i=content_id,
            message=_build_purchase_message(goods["sub"]),
            token=token,
        )
        if delivery_status == 200:
            await rq.update_delivery_status(user_id, 1)
    else:
        logger.info("Товар уже был отправлен покупателю")


async def check_new_orders(
    session: aiohttp.ClientSession,
    top: int = 3,
    token: str = None,
) -> None:
    last_sales = await return_last_sales(session, top=top, token=token)
    for sale in last_sales['sales']:
        order_info = await get_order_info(session, sale['invoice_id'], token=token)
        content_id = order_info['content']['content_id']
        if order_info['content']['invoice_state'] >= 3 <= 4:
            await rq.set_user(_ggsel_user_id(content_id))
            logger.info(
                "Оплаченный заказ #%s\ninv_id: %s\noption id: %s",
                content_id,
                sale['invoice_id'],
                order_info['content']['options'][0]['user_data_id'],
            )
            order_id_check = await rq.get_full_transaction_info_by_id(
                _ggsel_user_id(content_id),
            )
            order_params = await get_order_params(order_info)
            if order_id_check == 404:
                logger.info("Новый заказ")
                await order_register_routine(
                    order_info, order_params["days"],
                    order_params["template"], session, token, order_params['hwid'], order_params["outer_squad"],
                )
            else:
                logger.info(
                    "Заказ уже зарегистрирован в базе, delivery_status: %s",
                    order_id_check['delivery_status'],
                )
                await order_already_registered_routine(
                    order_id_check, order_info, order_params["days"],
                    order_params["template"], session, token, order_params['hwid'], order_params["outer_squad"],
                )
        else:
            logger.info("Заказ оплачен либо отменен: %s", sale['invoice_id'])
            await rq.set_user(_ggsel_user_id(content_id))


async def order_delivery_loop() -> None:
    async with aiohttp.ClientSession(base_url=secrets.get('ggsel_base_url')) as session:
        while True:
            # NOTE: error_counter сбрасывается каждую итерацию — возможный баг,
            # но оставлено как есть, чтобы не менять поведение.
            error_counter = 0
            try:
                token = await get_token(session)
                await check_new_orders(
                    session,
                    top=secrets.get('ggsel_top_value'),
                    token=token,
                )
            except Exception as e:
                error_counter += 1
                logger.error("Ошибка при проверке новых заказов: %s", e)
                if error_counter > secrets.get('ggsel_error_threshold'):
                    await send_alert(
                        f"Ошибка при проверке новых заказов: {e}\n"
                        f" Неудачных запросов подряд: {error_counter}",
                        "GGSELL",
                    )
            await asyncio.sleep(secrets.get('ggsel_check_interval') * 60)
