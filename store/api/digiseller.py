import hashlib
import logging
import uuid
from typing import Any, Optional

import store.tools as tools

import store.database.requests as rq

from store.settings import secrets

logger = logging.getLogger(__name__)


def generate_signature(
    id_value: Any,
    inv_value: Any,
    password: Any,
    model: str = "md5",
) -> Optional[str]:
    """
    Формирует MD5-подпись с автоматическим преобразованием типов
    """
    # Преобразуем все значения в строки
    id_str = str(id_value) if id_value is not None else ""
    inv_str = str(inv_value) if inv_value is not None else ""
    password_str = str(password) if password is not None else ""
    if model == "md5":
        # Формируем строку для подписи
        signature_string = f"{id_str}:{inv_str}:{password_str}"
        # Вычисляем MD5
        return hashlib.md5(signature_string.encode('utf-8')).hexdigest()
    if model == 'sha256':
        signature_string = f"{id_str};{inv_str};{password_str}"
        return hashlib.sha256(signature_string.encode('utf-8')).hexdigest()
    else:
        return None


async def payment_async_logic(payment_data: dict[str, Any]) -> Any:
    logger.info(f"Получен вебхук от магазина: {payment_data}")
    if 'id' not in payment_data or 'inv' not in payment_data or 'options' not in payment_data:
        return 400
    if await rq.item_id_exists(int(payment_data['id'])):
        logger.info('Id магазина обнаружен')
        dig_username = "dig_id" + payment_data["inv"]
        async with rq.get_session() as session:
            order_id_check = await rq.get_full_transaction_info(payment_data["inv"], session=session)
            user_info = await tools.get_user_info(dig_username)
            if user_info == 404:
                logger.info('Регистрация новой транзакции')
                sign = generate_signature(
                    payment_data['id'],
                    payment_data['inv'],
                    secrets.get('dig_pass'),
                )
                logger.debug(f"Computed sign: {sign}")
                logger.debug(f"Received sign: {payment_data.get('sign')}")
                if payment_data.get('sign') == sign:
                    logger.info('Подпись подтверждена')
                    order_params = await tools.parse_order_params(
                        item_id=payment_data['id'],
                        options=payment_data['options'],
                        id_key='id',
                        data_key='user_data',
                    )
                    days = order_params['days'] if order_params['days'] is not None else 30
                    hwid = order_params['hwid']
                    external_sq = order_params['outer_squad']
                    internal_sq = order_params['template']
                    await rq.set_user(int(f"44{payment_data['inv']}"), session=session)
                    await rq.create_transaction(
                        user_tg_id=int(f"44{payment_data['inv']}"),
                        user_transaction=str(uuid.uuid4()),
                        username=dig_username,
                        days=days,
                        session=session,
                    )
                    goods = await tools.create_subscription_for_order(content_id=payment_data["inv"],
                                                                      days=days,
                                                                      email=f"{payment_data['inv']}@cheeze.com",
                                                                      template=internal_sq,
                                                                      outer_squad_id=external_sq,
                                                                      hwid=hwid,
                                                                      store_name="DIG",
                                                                      user_info=user_info)
                    return goods["sub"]
                else:
                    return 400
            else:
                return user_info['subscription_url']
