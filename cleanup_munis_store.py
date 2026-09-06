"""Разовая чистка канала MUNIS STORE: посты-прайсы и навигация.

Удаляет 36 постов каталога (2263-2298) и навигационное сообщение (2301).
Не трогает приветствие 2299 и рекламные посты 2165-2222.

Тексты сохранены в _backup_munis_store.json. Telegram не восстанавливает
удалённые сообщения — вернуть можно только текст, но не сами посты.

Запуск:  .venv/bin/python cleanup_munis_store.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

import aiohttp
from dotenv import load_dotenv

from bot_api import BotApi

CHAT = "@iphone_moscow_98"
PRICE_POSTS = list(range(2263, 2299))
NAV_POST = 2301
TEST_POSTS = [2307, 2308]
DELETE_DELAY_SECONDS = 1.0

log = logging.getLogger("cleanup")


async def run(dry_run: bool) -> int:
    load_dotenv(".env")
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        log.error("Не задан BOT_TOKEN в .env")
        return 1

    targets = TEST_POSTS + PRICE_POSTS + [NAV_POST]
    log.info("К удалению %d сообщений: %s", len(targets), targets)
    if dry_run:
        log.info("Пробный режим: ничего не удалено. Повторите с --yes")
        return 0

    async with aiohttp.ClientSession() as session:
        api = BotApi(session, token)

        probe = targets[0]
        if await api.delete_message(CHAT, probe) is None:
            log.error(
                "Пробное удаление %d не прошло — остальные не трогаю. "
                "Похоже, Bot API не даёт удалять эти сообщения так же, "
                "как не давал их править.", probe,
            )
            return 1
        log.info("Пробное удаление %d прошло, продолжаю", probe)

        deleted, failed = 1, []
        for message_id in targets[1:]:
            await asyncio.sleep(DELETE_DELAY_SECONDS)
            if await api.delete_message(CHAT, message_id) is None:
                failed.append(message_id)
                log.warning("Не удалось удалить %d", message_id)
            else:
                deleted += 1
                log.info("Удалено %d", message_id)

    log.info("Готово: удалено %d, не удалось %d %s", deleted, len(failed), failed or "")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="подтвердить удаление")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    return asyncio.run(run(dry_run=not args.yes))


if __name__ == "__main__":
    raise SystemExit(main())
