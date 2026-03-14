import uuid
import time
import store.database.requests as rq
from store.notify import send_tg_alert
from store.settings import secrets
from store.settings import backend_bot as bot
import store.api.remnawave.api as rem

async def create_subscription_for_order(content_id, days: int, template,
                                        store_name: str = "GG",
                                        email: str = None,
                                        hwid: int = None,
                                        outer_squad_id: str = None,
                                        user_info=None):
    if user_info is None:
        user_info = await get_user_info(f"{store_name.lower()}_id{content_id}")
    if user_info == 404:
        usrid = uuid.uuid4()
        buyer_nfo = await add_new_user_info(
            f"{store_name.lower()}_id{content_id}",
            usrid,
            limit=0,
            expire_days=days,
            squad_id=template,
            email=email,
            hwid=hwid,
            outer_squad_id=outer_squad_id
        )
        print('Отправка ссылки на подписку')
        print(buyer_nfo['subscription_url'])
        await send_tg_alert(message=f"<b>⚠️ New {store_name.lower()} Order</b>\n"
                                    f"<b>🎫 OrderId: </b><code>{content_id}</code>\n"
                                    f"<b>👤 Email: </b><code>{email if email is not None else 'None'}</code>\n"
                                    f"<b>📱 HWID Limit: </b><code>{hwid if hwid is not None else 'default'}</code>\n"
                                    f"<b>📆 Days: </b>{days}\n"
                                    f"<b>💻 Vless uuid: </b><code>{usrid}</code>\n"
                                    f"<b>🔗 Link: </b><code>{buyer_nfo['subscription_url']}</code>",
                            store_name=f"{store_name}")
        subscription_link = buyer_nfo['subscription_url']
        result = {"sub": subscription_link}
        return result
    else:
        print('Пользователь уже существует')
        subscription_link = user_info['subscription_url']
        result = {"sub": subscription_link}
        return result

async def add_new_user_info(
    name: str,
    userid: int,
    limit: int = 0,
    expire_days: int = 30,
    email: str = None,
    description: str = "created by backend v2",
    squad_id: str = secrets.get('rw_free_id'),
    hwid: int = None,
    outer_squad_id: str = None,
):
    try:
        # Защита от передачи UNIX timestamp вместо дней
        if expire_days > 10000:
            current_time = time.time()
            expire_days = max(1, round((expire_days - current_time) / (24 * 60 * 60)))
            print(f"Warning: expire_days was UNIX timestamp, converted to {expire_days} days")

        if email is None:
            email = f"{name}@marzban.ru"

        buyer_nfo = await rem.create_user(
            username=name,
            days=expire_days,
            limit_gb=limit,
            descr=description,
            email=email,
            squad_id=squad_id,
            telegram_id=None,
            hwid_device_limit=hwid,
            external_squad_uuid=outer_squad_id
        )

        if buyer_nfo and buyer_nfo.get("uuid"):
            await rq.update_user_api_info(
                tg_id=userid,
                username=name,
                vless_uuid=buyer_nfo.get("uuid"),
                api_provider="remnawave"
            )
            print(f'DB updated with RemnaWave user info for {name}')

        return buyer_nfo

    except Exception as e:
        print(f"Error adding new user: {e}")
        return None

async def get_user_info(username):
    try:
        user_info = await rem.get_user_from_username(username)
        if user_info:
            expire = user_info.get("expire")
            if expire is not None:
                if hasattr(expire, 'timestamp'):
                    expire = int(expire.timestamp())
                else:
                    expire = int(expire) if expire else None

            return {
                "status": "active",
                "expire": expire,
                "subscription_url": user_info.get("subscription_url"),
                "data_limit": None
            }
        return 404
    except Exception as e:
        print(f"Error getting user info: {e}")
        return 404