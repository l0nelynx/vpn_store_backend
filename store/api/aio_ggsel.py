import aiohttp
import asyncio
import json
import time
import hashlib
import uuid

import store.api.marzban.templates as templates
from store.settings import secrets
from store.api.digiseller import get_variant_info, JSON_PATH
import store.database.requests as rq
from store.notify import send_tg_alert as send_alert
from store.tools import create_subscription_for_order


async def get_token(session):
    timestamp = time.time()
    sign = f"{secrets.get('ggsel_api_key')}"+f"{timestamp}"
    sign = hashlib.sha256(sign.encode("utf-8")).hexdigest()
    payload = json.dumps({
      "seller_id": secrets.get("ggsel_seller_id"),
      "timestamp": timestamp,
      "sign": f"{sign}"
    })
    print(payload)
    headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    }
    async with session.post("/api_sellers/api/apilogin",
                           data=payload, headers=headers) as response:
        data = await response.read()
        print(data.decode("utf-8"))
        data = json.loads(data.decode("utf-8"))
        return data['token']

async def send_message(session, id_i: int, message: str, token: str):
    success_counter = 0
    while success_counter <= secrets.get('ggsel_request_retries'):
        payload = json.dumps({
            "message": f"{message}"
        })
        headers = {
            'Content-Type': 'application/json'
        }
        async with session.post(f"/api_sellers/api/debates/v2?token={token}&id_i={id_i}",
                               data=payload, headers=headers) as response:
            status = response.status
            print(f'Send goods:{status}')
            data = await response.read()
            if status == 200:
                success_counter = secrets.get('ggsel_request_retries')+1
                await send_alert(f"Товар успешно отправлен\nСодержимое ответа:[{status}]{data.decode('utf-8')}\n<b><a href='https://seller.ggsel.net/messages?chatId={id_i}'>Чат</a></b>",
                                 "GGSELL")
                # await rq.update_delivery_status(int(f"99{id_i}"), 1)
                return 200
            else:
                print(data.decode("utf-8"))
                await send_alert(f"Ошибка отправки товара:\n[{status}]:{data.decode('utf-8')}\nПопытка: {success_counter}/{secrets.get('ggsel_request_retries')}\nПовтор через {secrets.get('ggsel_retry_timeout')} секунд",
                                 "GGSELL")
                success_counter +=1
                await asyncio.sleep(secrets.get('ggsel_retry_timeout'))
                return 400

async def return_last_sales(session, top: int = 3, token: str = None):
    headers = {
        'Accept': 'application/json',
        'locale': 'ru-RU'
    }
    async with session.get(f"/api_sellers/api/seller-last-sales?token={token}&seller_id={secrets.get('ggsel_seller_id')}&top={top}",
                          headers=headers) as response:
        status = response.status
        print(status)
        data = await response.read()
        print(data.decode("utf-8"))
        return json.loads(data.decode("utf-8"))

async def get_order_info(session, inv_id: int, token: str):
    headers = {
        'Accept': 'application/json',
        'locale': 'ru-RU'
    }
    async with session.get(f"/api_sellers/api/purchase/info/{inv_id}?token={token}",
                          headers=headers) as response:
        data = await response.read()
        print(data.decode("utf-8"))
        return json.loads(data.decode("utf-8"))

async def get_order_params(order_info):
    index_tax = int(not order_info['content']['options'][0]['name'] == 'Тариф')
    merchant_id = order_info['content']['options'][index_tax]['id']
    tariff_id = order_info['content']['options'][index_tax]['user_data_id']
    print(f"Length: {len(order_info['content']['options'])}")
    location_param_id = order_info['content']['options'][index_tax ^ 1]['id']
    location_id = order_info['content']['options'][index_tax ^ 1]['user_data_id']
    location = get_variant_info(JSON_PATH, location_param_id, location_id, 'template_name')
    days = get_variant_info(JSON_PATH, merchant_id, tariff_id, 'days')
    template = getattr(templates, location)
    print(f'Выбран шаблон: {template}')
    return {"days": days, "template": template}

async def order_register_routine(order_info, days, template, session, token):
    await send_alert('Найден новый оплаченный заказ, регистрация заказа', "GGSELL")
    await rq.create_transaction(user_tg_id=int(f"99{order_info['content']['content_id']}"),
                                user_transaction=f"{uuid.uuid4()}",
                                username=f"99{order_info['content']['content_id']}",
                                days=days)
    goods = await create_subscription_for_order(order_info['content']['content_id'], days, template)
    await asyncio.sleep(secrets.get('ggsel_retry_timeout'))
    await send_alert('Подписка сформирована', "GGSELL")
    delivery_status = await send_message(session, id_i=order_info['content']['content_id'],
                                         message=f'Спасибо за покупку!\n Ваша V2Ray ссылка для подписки : {goods["sub"]} \n'
                                                 f'Рекомендуем использовать именно подписку, т.к. она позволяет:\n'
                                                 f'- упростить процесс подключения на любом устройстве - достаточно просто открыть ее в браузере\n'
                                                 f'- автоматически обновлять конфигурации, когда мы обновляем их для лучшей работы сервиса\n'
                                                 f'- отображать срок истечения подписки\n'
                                                 f'- следить за потреблением трафика\n', token=token)
    if delivery_status == 200:
        await rq.update_delivery_status(int(f"99{order_info['content']['content_id']}"), 1)


async def order_already_registered_routine(order_id_check, order_info, days, template, session, token):
    if order_id_check['delivery_status'] == 0:
        goods = await create_subscription_for_order(order_info['content']['content_id'], days, template)
        delivery_status = await send_message(session, id_i=order_info['content']['content_id'],
                                             message=f'Спасибо за покупку!\n Ваша V2Ray ссылка для подписки : {goods["sub"]} \n'
                                                     f'Рекомендуем использовать именно подписку, т.к. она позволяет:\n'
                                                     f'- упростить процесс подключения на любом устройстве - достаточно просто открыть ее в браузере\n'
                                                     f'- автоматически обновлять конфигурации, когда мы обновляем их для лучшей работы сервиса\n'
                                                     f'- отображать срок истечения подписки\n'
                                                     f'- следить за потреблением трафика\n', token=token)
        if delivery_status == 200:
            await rq.update_delivery_status(int(f"99{order_info['content']['content_id']}"), 1)
        await send_message(session, id_i=order_info['content']['content_id'],
                           message=f'VLESS ключ: {goods["vless_0"]} \n{goods["vless_1"]}', token=token)
    else:
        print('Товар уже был отправлен покупателю')

async def check_new_orders(session, top: int = 3, token: str = None):
    last_sales = await return_last_sales(session, top=top, token=token)
    for sale in last_sales['sales']:
        order_info = await get_order_info(session, sale['invoice_id'], token=token)
        if order_info['content']['invoice_state'] >= 3 <= 4:
            await rq.set_user(int(f"99{order_info['content']['content_id']}"))
            print(f"Оплаченный заказ #{order_info['content']['content_id']}\ninv_id: "
                  f"{sale['invoice_id']}\noption id: {order_info['content']['options'][0]['user_data_id']}")
            order_id_check = await rq.get_full_transaction_info_by_id(int(f"99{order_info['content']['content_id']}"))
            order_params = await get_order_params(order_info)
            if order_id_check == 404:
                print('Новый заказ')
                await order_register_routine(order_info, order_params["days"],
                                             order_params["template"], session, token)
            else:
                print('Заказ уже зарегистрирован в базе')
                print('Order delivery status:', order_id_check['delivery_status'])
                await order_already_registered_routine(order_id_check, order_info, order_params["days"],
                                                       order_params["template"], session, token)
        else:
            print(f"Заказ оплачен либо отменен: {sale['invoice_id']}")
            await rq.set_user(int(f"99{order_info['content']['content_id']}"))


async def order_delivery_loop():
    async with aiohttp.ClientSession(base_url=secrets.get('ggsel_base_url')) as session:
        while True:
            error_counter = 0
            try:
                token = await get_token(session)
                await check_new_orders(session, top=secrets.get('ggsel_top_value'), token=token)
                # error_counter = 0
            except Exception as e:
                error_counter += 1
                print(f"Ошибка при проверке новых заказов: {e}")
                if error_counter > secrets.get('ggsel_error_threshold'):
                    await send_alert(f"Ошибка при проверке новых заказов: {e}\n Неудачных запросов подряд: {error_counter}", "GGSELL")
            await asyncio.sleep(secrets.get('ggsel_check_interval')*60)
