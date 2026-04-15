import logging

from store.settings import backend_bot as bot
from store.settings import secrets

logger = logging.getLogger(__name__)

async def webhook_tg_notify(payment_data, store_name: str):
    logging.info(f"Получен вебхук от магазина: {payment_data}")
    await bot.send_message(chat_id=secrets.get('admin_id'),
                           text=f"<b>{store_name} WEBHOOK:</b>\n\n"
                                f"<b>Content: \n</b><code>{payment_data}</code>",
                           parse_mode="HTML")
    return 200

async def send_tg_alert(message: str, store_name: str):
    logger.info(message)
    await bot.send_message(chat_id=secrets.get('admin_id'),
                           text=f"<b>{store_name} ALERT</b>\n\n"
                                f"{message}",
                           parse_mode="HTML",
                           disable_notification=True)