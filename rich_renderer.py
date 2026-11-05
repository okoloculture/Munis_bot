"""Сборка постов категорий в виде таблиц Rich Messages (Bot API 10.1+).

Rich-сообщение принимает до 32768 символов текста — в восемь раз больше
обычного, поэтому категория почти всегда помещается в один пост. Таблица
в две колонки: название из опта дословно и цена с наценкой.
"""

from __future__ import annotations

import html
from typing import Sequence

from markup import MarkupTier, apply_markup
from renderer import distribute, parse_position, split_blocks

RICH_MAX_TEXT = 32768
# Лимит считается по тексту без разметки; запас — под заголовок, «₽» и
# пересчитанные цены, которые бывают на разряд длиннее закупочных.
RICH_CAPACITY = 30000
PRICE_HEADER = "Цена"


def _row(line: str, tiers: Sequence[MarkupTier], round_to: int) -> str:
    parsed = parse_position(line)
    if parsed is None:
        # Строка без цены (подзаголовок, примечание) — на всю ширину таблицы.
        return f'<tr><td colspan="2"><b>{html.escape(line.strip())}</b></td></tr>'
    name, price = parsed
    retail = apply_markup(price, tiers, round_to)
    return f"<tr><td>{html.escape(name)}</td><td>{retail} ₽</td></tr>"


def render_rich_message(
    title: str,
    part_no: int,
    total_parts: int,
    lines: Sequence[str],
    tiers: Sequence[MarkupTier],
    round_to: int = 0,
) -> str:
    """Собрать HTML одного rich-поста категории: таблица с шапкой «Категория | Цена»."""
    suffix = f" (часть {part_no}/{total_parts})" if total_parts > 1 else ""
    header = (
        f"<table bordered><tr><th>{html.escape(title + suffix)}</th>"
        f"<th>{PRICE_HEADER}</th></tr>"
    )
    rows = [_row(line, tiers, round_to) for line in lines if line.strip()]
    return "\n".join([header, *rows]) + "</table>"


def build_rich_messages(
    title: str,
    lines: Sequence[str],
    slots: int,
    tiers: Sequence[MarkupTier],
    round_to: int = 0,
    capacity: int = RICH_CAPACITY,
) -> list[str]:
    """Разложить строки категории по `slots` rich-постам; не влезло — частей больше."""
    parts = distribute(split_blocks(lines), slots, capacity)
    total = len(parts)
    return [
        render_rich_message(title, index + 1, total, part, tiers, round_to)
        for index, part in enumerate(parts)
    ]
