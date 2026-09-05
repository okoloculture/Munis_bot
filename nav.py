"""Навигационное сообщение с кнопками-ссылками на посты категорий."""

from __future__ import annotations

import html
from typing import Sequence

DEFAULT_NAV_TEXT = "ВЫБЕРИТЕ НУЖНУЮ КАТЕГОРИЮ✅"
DEFAULT_COLUMNS = 3
MAX_BUTTON_TEXT = 64

# Telegram растягивает кнопки ряда на равную ширину, поэтому длинный ярлык
# рядом с двумя короткими сминается. Ряд набирается, пока суммарная длина
# подписей не превысит этот бюджет в символах.
DEFAULT_ROW_WIDTH = 30

# Значения, которые принимает InlineKeyboardButton.style.
# Проверено на живом Bot API: "positive"/"negative" отвергаются.
BUTTON_STYLES = ("default", "primary", "success", "danger")
DEFAULT_BUTTON_STYLE = "default"


class ButtonStyleError(ValueError):
    """Недопустимый стиль кнопки."""


def validate_style(style: str) -> str:
    """Проверить стиль кнопки по списку, принимаемому Bot API."""
    if style not in BUTTON_STYLES:
        raise ButtonStyleError(
            f"Недопустимый стиль кнопки {style!r}; допустимы: {', '.join(BUTTON_STYLES)}"
        )
    return style


def make_button(text: str, url: str, style: str = DEFAULT_BUTTON_STYLE) -> dict:
    """Собрать url-кнопку; стиль default не передаём — он и так подразумевается."""
    button = {"text": text[:MAX_BUTTON_TEXT], "url": url}
    if style != DEFAULT_BUTTON_STYLE:
        button["style"] = validate_style(style)
    return button


def channel_link_id(chat_id: str | int) -> str:
    """Из -100XXXX получить XXXX для ссылок вида t.me/c/XXXX/<id>."""
    text = str(chat_id).strip()
    if text.startswith("-100"):
        return text[4:]
    return text.lstrip("-")


def message_link(chat_id: str | int, username: str | None, message_id: int) -> str:
    """Ссылка на пост: публичная по username, иначе внутренняя t.me/c/."""
    if username:
        return f"https://t.me/{username.lstrip('@')}/{message_id}"
    return f"https://t.me/c/{channel_link_id(chat_id)}/{message_id}"


def pack_rows(
    labels: Sequence[str],
    columns: int = DEFAULT_COLUMNS,
    row_width: int = DEFAULT_ROW_WIDTH,
) -> list[list[int]]:
    """Разложить подписи по рядам: не длиннее columns кнопок и row_width символов.

    Возвращает индексы подписей по рядам. Одиночная длинная подпись занимает
    весь ряд — так она не сминается соседями.
    """
    if columns < 1:
        raise ValueError("columns должен быть >= 1")
    if row_width < 1:
        raise ValueError("row_width должен быть >= 1")

    rows: list[list[int]] = []
    row: list[int] = []
    width = 0
    for index, label in enumerate(labels):
        length = len(label)
        if row and (len(row) >= columns or width + length > row_width):
            rows.append(row)
            row, width = [], 0
        row.append(index)
        width += length
    if row:
        rows.append(row)
    return rows


def build_keyboard(
    entries: Sequence[tuple[str, str]],
    columns: int = DEFAULT_COLUMNS,
    extra_rows: Sequence[Sequence[dict]] = (),
    style: str = DEFAULT_BUTTON_STYLE,
    row_width: int = DEFAULT_ROW_WIDTH,
) -> dict:
    """Собрать inline-клавиатуру: категории рядами + дополнительные ряды снизу."""
    labels = [title for title, _ in entries]
    rows = [
        [make_button(*entries[index], style) for index in indexes]
        for indexes in pack_rows(labels, columns, row_width)
    ]
    rows.extend([list(extra) for extra in extra_rows if extra])
    return {"inline_keyboard": rows}


def render_text(text: str = DEFAULT_NAV_TEXT) -> str:
    """HTML навигационного сообщения."""
    return f"<b>{html.escape(text)}</b>"
