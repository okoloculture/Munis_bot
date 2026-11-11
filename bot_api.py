"""Тонкий клиент Telegram Bot API с ретраями и обработкой 429."""

from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

try:
    from python_socks import ProxyError as _ProxyError
except ImportError:
    class _ProxyError(Exception):
        pass

log = logging.getLogger(__name__)

API_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=15)
UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=120, connect=15)
API_RETRIES = 3
MAX_RATE_LIMIT_SLEEP = 90

NOT_MODIFIED = {"not_modified": True}
# Сообщения, которое правим, в канале больше нет — его удалили руками.
# Ретрай тут бесполезен, вызывающий код должен забыть этот message_id.
MESSAGE_GONE = {"message_gone": True}


class BotApi:
    """Обёртка над api.telegram.org/bot<token>."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        *,
        http_proxy: str | None = None,
    ) -> None:
        self._session = session
        self._token = token
        self._http_proxy = http_proxy

    async def call(self, method: str, payload: dict) -> dict | None:
        """Вызвать метод API. Возвращает result или None при неустранимой ошибке."""
        url = f"https://api.telegram.org/bot{self._token}/{method}"

        for attempt in range(1, API_RETRIES + 1):
            try:
                async with self._session.post(
                    url, json=payload, timeout=API_TIMEOUT, proxy=self._http_proxy,
                ) as resp:
                    result = await resp.json()

                if result.get("ok"):
                    return result.get("result")

                description = result.get("description", "")
                if "message is not modified" in description:
                    return NOT_MODIFIED
                if "message to edit not found" in description:
                    return MESSAGE_GONE

                if result.get("error_code") == 429:
                    retry_after = int(result.get("parameters", {}).get("retry_after", 1))
                    wait = min(retry_after + 1, MAX_RATE_LIMIT_SLEEP)
                    log.warning(
                        "Лимит запросов на %s, пауза %d с (попытка %d/%d)",
                        method, wait, attempt, API_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue

                log.error("Ошибка Bot API на %s: %s", method, result)
                return None
            except asyncio.TimeoutError:
                log.warning("Таймаут %s (попытка %d/%d)", method, attempt, API_RETRIES)
            except (aiohttp.ClientError, _ProxyError) as exc:
                log.warning(
                    "Сетевая ошибка %s (попытка %d/%d): %s", method, attempt, API_RETRIES, exc,
                )

            if attempt < API_RETRIES:
                await asyncio.sleep(2 * attempt)

        log.error("Отказ от %s после %d попыток", method, API_RETRIES)
        return None

    async def _upload(
        self,
        method: str,
        fields: dict[str, str],
        files: dict[str, tuple[str, bytes]],
    ) -> dict | None:
        """Вызвать метод API с multipart-загрузкой файлов {поле: (имя, байты)}.

        FormData одноразова, поэтому тело собирается заново на каждой попытке.
        """
        url = f"https://api.telegram.org/bot{self._token}/{method}"

        for attempt in range(1, API_RETRIES + 1):
            form = aiohttp.FormData()
            for key, value in fields.items():
                form.add_field(key, value)
            for field_name, (filename, payload) in files.items():
                form.add_field(
                    field_name, payload, filename=filename,
                    content_type="application/octet-stream",
                )

            try:
                async with self._session.post(
                    url, data=form, timeout=UPLOAD_TIMEOUT, proxy=self._http_proxy,
                ) as resp:
                    result = await resp.json()

                if result.get("ok"):
                    return result.get("result")

                if "message is not modified" in result.get("description", ""):
                    return NOT_MODIFIED
                if "message to edit not found" in result.get("description", ""):
                    return MESSAGE_GONE

                if result.get("error_code") == 429:
                    retry_after = int(result.get("parameters", {}).get("retry_after", 1))
                    wait = min(retry_after + 1, MAX_RATE_LIMIT_SLEEP)
                    log.warning("Лимит запросов на %s, пауза %d с", method, wait)
                    await asyncio.sleep(wait)
                    continue

                log.error("Ошибка Bot API на %s: %s", method, result)
                return None
            except asyncio.TimeoutError:
                log.warning("Таймаут %s (попытка %d/%d)", method, attempt, API_RETRIES)
            except (aiohttp.ClientError, _ProxyError) as exc:
                log.warning(
                    "Сетевая ошибка %s (попытка %d/%d): %s", method, attempt, API_RETRIES, exc,
                )

            if attempt < API_RETRIES:
                await asyncio.sleep(2 * attempt)

        log.error("Отказ от %s после %d попыток", method, API_RETRIES)
        return None

    async def send_document(
        self,
        chat_id: str,
        filename: str,
        payload: bytes,
        *,
        caption: str = "",
        disable_notification: bool = True,
    ) -> dict | None:
        """Загрузить файл в чат новым сообщением."""
        fields = {
            "chat_id": chat_id,
            "parse_mode": "HTML",
            "disable_notification": "true" if disable_notification else "false",
        }
        if caption:
            fields["caption"] = caption
        return await self._upload("sendDocument", fields, {"document": (filename, payload)})

    async def edit_message_document(
        self,
        chat_id: str,
        message_id: int,
        filename: str,
        payload: bytes,
        *,
        caption: str = "",
    ) -> dict | None:
        """Заменить файл в уже отправленном сообщении."""
        media = {"type": "document", "media": "attach://upload"}
        if caption:
            media["caption"] = caption
            media["parse_mode"] = "HTML"
        fields = {
            "chat_id": chat_id,
            "message_id": str(message_id),
            "media": json.dumps(media, ensure_ascii=False),
        }
        return await self._upload("editMessageMedia", fields, {"upload": (filename, payload)})

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
    ) -> dict | None:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.call("editMessageText", payload)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        disable_notification: bool = True,
        reply_markup: dict | None = None,
    ) -> dict | None:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": disable_notification,
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def _rich(self, method: str, payload: dict, html_text: str, photos: dict[str, bytes] | None) -> dict | None:
        """Вызвать rich-метод; фото грузятся файлами и подставляются по tg://photo?id=.

        Ссылку на фото Telegram принимать отказывается (проверено: и <img src=https…>,
        и media по URL падают), поэтому только загрузка multipart через attach://.
        """
        rich: dict = {"html": html_text}
        if not photos:
            return await self.call(method, {**payload, "rich_message": rich})
        rich["media"] = [
            {"id": photo_id, "media": {"type": "photo", "media": f"attach://{photo_id}"}}
            for photo_id in photos
        ]
        fields = {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for key, value in {**payload, "rich_message": rich}.items()
        }
        files = {photo_id: (f"{photo_id}.jpg", data) for photo_id, data in photos.items()}
        return await self._upload(method, fields, files)

    async def send_rich_message(
        self,
        chat_id: str,
        html_text: str,
        *,
        disable_notification: bool = True,
        reply_markup: dict | None = None,
        photos: dict[str, bytes] | None = None,
    ) -> dict | None:
        """Отправить rich-сообщение (таблицы, заголовки, фото); разметка — HTML."""
        payload: dict = {"chat_id": chat_id, "disable_notification": disable_notification}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._rich("sendRichMessage", payload, html_text, photos)

    async def edit_rich_message(
        self,
        chat_id: str,
        message_id: int,
        html_text: str,
        *,
        reply_markup: dict | None = None,
        photos: dict[str, bytes] | None = None,
    ) -> dict | None:
        """Заменить содержимое сообщения rich-разметкой.

        Проверено на живом канале: так правятся и rich-, и обычные сообщения —
        обычное при этом становится rich.
        """
        payload: dict = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._rich("editMessageText", payload, html_text, photos)

    async def delete_message(self, chat_id: str, message_id: int) -> dict | None:
        return await self.call("deleteMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
        })

    async def pin_message(self, chat_id: str, message_id: int) -> dict | None:
        return await self.call("pinChatMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": True,
        })

    async def unpin_message(self, chat_id: str, message_id: int) -> dict | None:
        return await self.call("unpinChatMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
        })

    async def get_me(self) -> dict | None:
        return await self.call("getMe", {})
