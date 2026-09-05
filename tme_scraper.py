"""Чтение публичных Telegram-каналов через веб-превью t.me/s/<channel>."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import aiohttp
from bs4 import BeautifulSoup

try:
    from python_socks import ProxyError as _ProxyError
except ImportError:  # python_socks не установлен — заглушка, которая никогда не бросается
    class _ProxyError(Exception):
        pass

log = logging.getLogger(__name__)

PAGE_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=15)
PAGE_RETRIES = 3
_USER_AGENT = "Mozilla/5.0"


@dataclass(frozen=True)
class ChannelMessage:
    """Одно сообщение канала с уже развёрнутым в \\n текстом."""

    message_id: int
    text: str


class ChannelFetchError(RuntimeError):
    """Не удалось прочитать страницу канала."""


def parse_page(html_text: str) -> list[ChannelMessage]:
    """Вытащить сообщения из HTML страницы t.me/s/<channel>."""
    soup = BeautifulSoup(html_text, "html.parser")
    messages: list[ChannelMessage] = []

    for node in soup.find_all("div", class_="tgme_widget_message"):
        post = node.get("data-post")
        if not post or "/" not in post:
            continue
        try:
            message_id = int(post.rsplit("/", 1)[1])
        except ValueError:
            continue

        text_node = node.find("div", class_="tgme_widget_message_text")
        if text_node is None:
            continue
        for br in text_node.find_all("br"):
            br.replace_with("\n")
        messages.append(ChannelMessage(message_id=message_id, text=text_node.get_text()))

    return messages


async def _fetch_page(
    session: aiohttp.ClientSession,
    channel: str,
    before: int | None,
    http_proxy: str | None,
) -> str:
    """Скачать одну страницу превью канала с ретраями."""
    url = f"https://t.me/s/{channel}"
    params = {"before": str(before)} if before is not None else None

    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            async with session.get(
                url,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=PAGE_TIMEOUT,
                proxy=http_proxy,
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                log.warning(
                    "t.me/s/%s before=%s: HTTP %d (попытка %d/%d)",
                    channel, before, resp.status, attempt, PAGE_RETRIES,
                )
        except asyncio.TimeoutError:
            log.warning(
                "Таймаут t.me/s/%s before=%s (попытка %d/%d)",
                channel, before, attempt, PAGE_RETRIES,
            )
        except (aiohttp.ClientError, _ProxyError) as exc:
            log.warning(
                "Сетевая ошибка t.me/s/%s before=%s (попытка %d/%d): %s",
                channel, before, attempt, PAGE_RETRIES, exc,
            )

        if attempt < PAGE_RETRIES:
            await asyncio.sleep(2 * attempt)

    raise ChannelFetchError(f"Не удалось прочитать t.me/s/{channel} (before={before})")


async def fetch_messages(
    session: aiohttp.ClientSession,
    channel: str,
    *,
    max_pages: int = 8,
    http_proxy: str | None = None,
    page_delay: float = 1.0,
) -> list[ChannelMessage]:
    """Прочитать до max_pages страниц истории канала, от свежих к старым.

    Возвращает сообщения, отсортированные по возрастанию message_id.
    """
    collected: dict[int, ChannelMessage] = {}
    before: int | None = None

    for page in range(max_pages):
        html_text = await _fetch_page(session, channel, before, http_proxy)
        messages = parse_page(html_text)
        if not messages:
            break

        new_ids = [m.message_id for m in messages if m.message_id not in collected]
        for message in messages:
            collected.setdefault(message.message_id, message)

        log.debug(
            "t.me/s/%s страница %d: %d сообщений (%d новых)",
            channel, page + 1, len(messages), len(new_ids),
        )
        if not new_ids:
            break

        before = min(m.message_id for m in messages)
        if before <= 1:
            break
        if page + 1 < max_pages:
            await asyncio.sleep(page_delay)

    return [collected[key] for key in sorted(collected)]
