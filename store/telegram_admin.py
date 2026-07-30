"""Optional Telegram admin commands, hosted by the worker process."""

from __future__ import annotations

import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from store.integrations.providers import ggsel
from store.settings import secrets

router = Router()


@router.message(Command("message"))
async def send_marketplace_message(message: Message) -> None:
    if not message.from_user or message.from_user.id != int(secrets.get("admin_id") or 0):
        return
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Использование: /message <content_id> <текст>")
        return
    try:
        content_id = int(args[1])
    except ValueError:
        await message.reply("content_id должен быть числом")
        return
    try:
        async with aiohttp.ClientSession() as http:
            await ggsel.send_message(http, content_id, args[2])
        await message.reply(f"Сообщение отправлено (content_id={content_id})")
    except Exception:
        await message.reply("Не удалось отправить сообщение; подробности записаны в журнал worker-а")
