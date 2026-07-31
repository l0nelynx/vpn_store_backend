"""Store worker: polling, durable outbox and optional Telegram admin bot."""

from __future__ import annotations

import asyncio
import logging
import os
import socket

from aiogram import Dispatcher

from store.database.models import async_main
from store.services.messaging import poll_unread_chats
from store.services.order_sync import sync_ggsel_orders
from store.services.pipelines import bootstrap_legacy_pipelines
from store.services.runtime import bootstrap_templates, claim_outbox, process_outbox_job
from store.settings import backend_bot, secrets
from store.telegram_admin import router as telegram_router

logger = logging.getLogger(__name__)


async def polling_loop() -> None:
    interval = max(10, int(secrets.get("ggsel_check_interval") or 1) * 60)
    top = int(secrets.get("ggsel_top_value") or 50)
    while True:
        try:
            await sync_ggsel_orders(top)
        except Exception:
            logger.exception("GGSel polling iteration failed")
        await asyncio.sleep(interval)


async def inbox_poll_loop() -> None:
    interval = max(30, int(secrets.get("inbox_poll_interval_seconds") or 120))
    while True:
        try:
            summary = await poll_unread_chats()
            if summary.get("notified") or summary.get("errors"):
                logger.info("Inbox unread poll: %s", summary)
        except Exception:
            logger.exception("Inbox unread poll iteration failed")
        await asyncio.sleep(interval)


async def outbox_loop() -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    while True:
        ids = await claim_outbox(worker_id, limit=20)
        if not ids:
            await asyncio.sleep(1)
            continue
        await asyncio.gather(*(process_outbox_job(job_id) for job_id in ids))


async def main() -> None:
    await async_main()
    await bootstrap_templates()
    await bootstrap_legacy_pipelines()
    tasks = [polling_loop(), outbox_loop(), inbox_poll_loop()]
    if backend_bot:
        dispatcher = Dispatcher()
        dispatcher.include_router(telegram_router)
        tasks.append(dispatcher.start_polling(backend_bot))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
