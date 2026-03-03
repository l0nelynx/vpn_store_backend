import uuid
import time
import store.database.requests as rq
from store.notify import send_tg_alert
from store.settings import secrets
from store.settings import backend_bot as bot
import store.api.remnawave.api as rem
import store.api.marzban as mz
import store.api.marzban.templates as templates

async def create_subscription_for_order(content_id, days: int, template):
    user_info = await get_user_info(f"gg_id{content_id}")
    if user_info == 404:
        usrid = uuid.uuid4()
        buyer_nfo = await add_new_user_info(
            f"gg_id{content_id}",
            usrid,
            limit=0,
            res_strat="no_reset",
            expire_days=days,
            template=template
        )
        print('Отправка ссылки на подписку')
        print(buyer_nfo['subscription_url'])
        await send_tg_alert(message=f"<b>GGsel Order</b>\n\n"
                                    f"<b>GGsel Id: </b><code>{content_id}<code>\n"
                                    f"<b>Days: </b>{days}\n"
                                    f"<b>Vless uuid: </b>{usrid}\n"
                                    f"<b>Link: </b><code>{buyer_nfo['subscription_url']}</code>",
                            store_name="GGSELL")
        subscription_link = buyer_nfo['subscription_url']
        print(buyer_nfo['links'][0])
        print(len(buyer_nfo['links']))
        vless_0 = buyer_nfo['links'][0]
        if len(buyer_nfo['links']) > 1:
            vless_1 = buyer_nfo['links'][1]
            result = {"sub": subscription_link,
                "vless_0": vless_0,
                "vless_1": vless_1}
        else:
            result = {"sub": subscription_link,
                "vless_0": vless_0,
                "vless_1": " "}
        return result
    else:
        print('Пользователь уже существует')
        subscription_link = user_info['subscription_url']
        vless_0 = user_info['links'][0]
        if len(user_info['links']) > 1:
            vless_1 = user_info['links'][1]
            result = {"sub": subscription_link,
                "vless_0": vless_0,
                "vless_1": vless_1}
        else:
            result = {"sub": subscription_link,
                "vless_0": vless_0,
                "vless_1": " "}
        return result

def time_to_unix(days: int):
    return int(days * 24 * 60 * 60)

async def add_new_user_info(name, userid, limit, res_strat, expire_days: int, template: dict = templates.vless_template, api: str = "marzban"):
    if api == "marzban":
        async with mz.MarzbanAsync() as marz:
            buyer_nfo = await marz.add_user(
                template=template,
                name=f"{name}",
                usrid=f"{userid}",
                limit=limit,
                res_strat=res_strat,  # no_reset day week month year
                expire=(int(time.time() + time_to_unix(expire_days)))
            )
        return buyer_nfo
    else:
        # REMNAWAVE INTEGRATION
        buyer_nfo = await rem.create_user(
            username= name,
            days= expire_days,
            limit_gb= limit,
            descr='created by backend v2'
        )
        db_upd_status = await rq.update_user_vless_uuid(name, buyer_nfo["uuid"])
        print('db is updated: ', db_upd_status)
        return buyer_nfo

async def get_user_info(username, api: str = "marzban"):
    if api == "marzban":
        async with mz.MarzbanAsync() as marz:
            user_info = await marz.get_user(name=username)
        return user_info
    else:
        # REMNAWAVE INTEGRATION
        user_info = await rem.get_user_from_username(username)
        return user_info