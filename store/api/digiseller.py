import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional
from uuid import UUID
import store.api.remnawave.squads as squads

import store.tools as tools
from pydantic import BaseModel
from store.settings import backend_bot as bot

import store.database.requests as rq

from store.settings import secrets

logger = logging.getLogger(__name__)

file_path = "dig_data.json"

config_path = Path(__file__).parent.parent.parent / file_path

JSON_PATH = config_path

_json_cache_data: dict | None = None
_json_cache_mtime: float = 0.0


def _load_json_cached(json_file_path: Path) -> dict | None:
    global _json_cache_data, _json_cache_mtime
    try:
        mtime = os.path.getmtime(json_file_path)
        if _json_cache_data is not None and mtime == _json_cache_mtime:
            return _json_cache_data
        with open(json_file_path, 'r') as stream:
            _json_cache_data = json.load(stream)
        _json_cache_mtime = mtime
        return _json_cache_data
    except Exception as e:
        logger.debug(f"Error loading JSON cache: {e}")
        return None


class DigisellerResponse(BaseModel):
    id: str
    inv: int
    goods: str
    error: str


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


def get_variant_info(
    json_file_path: Path,
    merchant_id: Any,
    variant_id: Any,
    field: Optional[str] = None,
) -> Optional[Any]:
    try:
        data = _load_json_cached(json_file_path)
        if data is None:
            return None

        variant_id_str = str(variant_id)
        variant_info = data['var_ids'][f'{merchant_id}']['variants'].get(variant_id_str)

        if variant_info is None:
            return None

        return variant_info if field is None else variant_info.get(field)

    except Exception as e:
        logger.debug(f"Произошла ошибка: {e}")
        return None


def extract_dig_items(secrets_in: Any) -> dict[int, Any]:
    result = {}
    index = 0
    while True:
        key = f"dig_item_id_{index}"
        value = secrets_in.get(key)
        if value is None:
            break
        result[index] = value
        index += 1
    return result


def check_id_exists_efficient(target_id: Any, secrets_in: Any) -> bool:
    dig_items = extract_dig_items(secrets_in)
    values_set = set(dig_items.values())
    return str(target_id) in values_set


async def payment_async_logic(payment_data: dict[str, Any]) -> Any:
    logger.info(f"Получен вебхук от магазина: {payment_data}")
    if 'id' not in payment_data or 'inv' not in payment_data or 'options' not in payment_data:
        return 400
    if check_id_exists_efficient(payment_data['id'], secrets):
        logger.info('Id магазина обнаружен')
        dig_username = "dig_id" + payment_data["inv"]
        async with rq.get_session() as session:
            order_id_check = await rq.get_full_transaction_info(payment_data["inv"], session=session)
            user_info = await tools.get_user_info(dig_username)
            if user_info == 404:
                logger.info('Регистрация новой транзакции')
                merchant_id = payment_data['options'][0]['id']
                tariff_id = payment_data['options'][0]['user_data']
                # days = get_variant_info(JSON_PATH, merchant_id, tariff_id, 'days')
                sign = generate_signature(
                    payment_data['id'],
                    payment_data['inv'],
                    secrets.get('dig_pass'),
                )
                logger.debug(f"Computed sign: {sign}")
                logger.debug(f"Received sign: {payment_data.get('sign')}")
                if payment_data.get('sign') == sign:
                    logger.info('Подпись подтверждена')
                    item_id = payment_data['id']
                    result = {}
                    for option in payment_data['options']:
                        params = await rq.get_order_params_dict(
                            item_id=item_id,
                            param_id=option['id'],
                            user_data_id=option['user_data'],
                        )
                        result.update(params)
                    days = int(result.get('days')) if result.get('days') else 30
                    hwid = int(result.get('hwid')) if result.get('hwid') else None
                    external_sq=result.get('external_sq')
                    internal_sq=result.get('location')
                    logger.debug("Order params from DB: %s", result)
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
