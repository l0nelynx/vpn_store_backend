import uuid
import time
import store.database.requests as rq
from store.notify import send_tg_alert
from store.settings import secrets
from store.settings import backend_bot as bot
import store.api.remnawave.api as rem
import store.api.marzban as mz
import store.api.marzban.templates as templates

async def create_subscription_for_order(content_id, days: int, template, store_name: str = "gg_id",):
    user_info = await get_user_info(f"{store_name}{content_id}")
    if user_info == 404:
        usrid = uuid.uuid4()
        buyer_nfo = await add_new_user_info(
            f"{store_name}{content_id}",
            usrid,
            limit=0,
            res_strat="no_reset",
            expire_days=days,
            template=template,
            squad_id=template
        )
        print('Отправка ссылки на подписку')
        print(buyer_nfo['subscription_url'])
        await send_tg_alert(message=f"<b>GGsel Order</b>\n\n"
                                    f"<b>GGsel Id: </b><code>{content_id}</code>\n"
                                    f"<b>Days: </b>{days}\n"
                                    f"<b>Vless uuid: </b>{usrid}\n"
                                    f"<b>Link: </b><code>{buyer_nfo['subscription_url']}</code>",
                            store_name=f"{store_name}")
        subscription_link = buyer_nfo['subscription_url']
        # print(buyer_nfo['links'][0])
        # print(len(buyer_nfo['links']))
        # vless_0 = buyer_nfo['links'][0]
        # if len(buyer_nfo['links']) > 1:
        #     vless_1 = buyer_nfo['links'][1]
        #     result = {"sub": subscription_link,
        #         "vless_0": vless_0,
        #         "vless_1": vless_1}
        # else:
        result = {"sub": subscription_link,
                "vless_0": "delete-me",
                "vless_1": "delete-me"}
        return result
    else:
        print('Пользователь уже существует')
        subscription_link = user_info['subscription_url']
        # vless_0 = user_info['links'][0]
        # if len(user_info['links']) > 1:
        #     vless_1 = user_info['links'][1]
        #     result = {"sub": subscription_link,
        #         "vless_0": vless_0,
        #         "vless_1": vless_1}
        # else:
        result = {"sub": subscription_link,
                "vless_0": "delete-me",
                "vless_1": "delete-me"}
        return result

def time_to_unix(days: int):
    return int(days * 24 * 60 * 60)

async def add_new_user_info(
    name: str,
    userid: int,
    limit: int = 0,
    res_strat: str = "no_reset",
    expire_days: int = 30,
    template: dict = templates.vless_template,
    api: str = "remnawave",
    email: str = None,
    description: str = "created by backend v2",
    squad_id: str = secrets.get('rw_free_id')
):
    """
    Добавляет нового пользователя в указанный API провайдер

    Args:
        name (str): Имя пользователя
        userid (int): ID пользователя (Telegram ID)
        limit (int): Лимит трафика в GB (0 = без лимита)
        res_strat (str): Стратегия сброса трафика (для Marzban: no_reset, day, week, month, year)
        expire_days (int): Количество дней действия подписки
        template (dict): Шаблон конфигурации (для Marзban)
        api (str): API провайдер (marzban или remnawave)
        email (str): Email пользователя (для RemnaWave)
        description (str): Описание пользователя
        squad_id (str): ID группы пользователей в RemnaWave

    Returns:
        dict: Информация о созданном пользователе
    """
    try:
        # Защита от передачи UNIX timestamp вместо дней
        # Если значение больше чем разумное количество дней (10 лет = 3650 дней),
        # то это вероятно UNIX timestamp
        if expire_days > 10000:
            # Это UNIX timestamp, преобразуем обратно в дни
            current_time = time.time()
            expire_days = max(1, round((expire_days - current_time) / (24 * 60 * 60)))
            print(f"Warning: expire_days was UNIX timestamp, converted to {expire_days} days")

        if api == "marzban":
            async with mz.MarzbanAsync() as marz:
                buyer_nfo = await marz.add_user(
                    template=template,
                    name=f"{name}",
                    usrid=f"{userid}",
                    limit=limit,
                    res_strat=res_strat,
                    expire=(int(time.time() + time_to_unix(expire_days)))
                )

            # Сохраняем информацию об API провайдере в БД
            await rq.update_user_api_info(
                username=name,
                api_provider="marzban"
            )
            return buyer_nfo

        elif api == "remnawave":
            # REMNAWAVE INTEGRATION с расширенными параметрами
            if email is None:
                email = f"{name}@marzban.ru"

            buyer_nfo = await rem.create_user(
                username=name,
                days=expire_days,
                limit_gb=limit,
                descr=description,
                email=email,
                squad_id=squad_id,
                telegram_id=None
            )

            if buyer_nfo and buyer_nfo.get("uuid"):
                # Сохраняем информацию об API провайдере и UUID в БД
                await rq.update_user_api_info(
                    tg_id=userid,
                    username=name,
                    vless_uuid=buyer_nfo.get("uuid"),
                    api_provider="remnawave"
                )
                print(f'DB updated with RemnaWave user info for {name}')

            return buyer_nfo
        else:
            print(f"Unknown API provider: {api}")
            return None

    except Exception as e:
        print(f"Error adding new user to {api}: {e}")
        return None

async def get_user_info(username, api: str = "remnawave"):
    """
    Получает информацию о пользователе из указанного API

    Args:
        username (str): Имя пользователя
        api (str): API провайдер (marzban или remnawave)

    Returns:
        dict: Информация о пользователе или 404 если пользователь не найден
    """
    try:
        if api == "marzban":
            async with mz.MarzbanAsync() as marz:
                user_info = await marz.get_user(name=username)
            return user_info
        elif api == "remnawave":
            # REMNAWAVE INTEGRATION
            user_info = await rem.get_user_from_username(username)
            if user_info:
                # Преобразуем expire в UNIX timestamp если это datetime объект
                expire = user_info.get("expire")
                if expire is not None:
                    # Если это datetime объект, преобразуем в UNIX timestamp
                    if hasattr(expire, 'timestamp'):
                        expire = int(expire.timestamp())
                    else:
                        # Если это уже число, оставляем как есть
                        expire = int(expire) if expire else None

                # Нормализуем ответ для совместимости
                return {
                    "status": "active",
                    "expire": expire,
                    "subscription_url": user_info.get("subscription_url"),
                    "data_limit": None  # RemnaWave может иметь лимит, нужно добавить
                }
            return 404
        else:
            print(f"Unknown API provider: {api}")
            return 404
    except Exception as e:
        print(f"Error getting user info from {api}: {e}")
        return 404