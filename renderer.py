"""Пересчёт цен и сборка сообщений для целевого канала.

Строки прайса переносятся дословно: меняется только число цены в конце строки.
Так ни одна позиция не теряется на разборе и не искажается название.
"""

from __future__ import annotations

import html
import math
import re
from typing import Sequence

from markup import MarkupTier, apply_markup

TELEGRAM_MAX_LEN = 4096

# Цена — последнее число в строке, отделённое пробелом или тире.
# Отсекаем артикулы (S24Ultra512) и слипшиеся с буквами числа.
_PRICE_LINE_RE = re.compile(
    r"^(?P<head>.*?[\s\-–—])(?P<price>\d{4,7})\s*$"
)
# Хвост «название — » отрезается вместе с не более чем одним тире,
# чтобы не откусить дефис внутри названия (Type-C, Wi-Fi).
_NAME_TAIL_RE = re.compile(r"\s*[-–—]?\s*$")
_MIN_PRICE = 1000

DEFAULT_PRICE_FORMAT = "{name} — {price} ₽"


class PriceFormatError(ValueError):
    """Шаблон строки цены задан некорректно."""


def validate_price_format(template: str) -> str:
    """Проверить, что шаблон содержит оба плейсхолдера и форматируется."""
    try:
        rendered = template.format(name="X", price=1)
    except (KeyError, IndexError, ValueError) as exc:
        raise PriceFormatError(f"Некорректный шаблон price_format: {exc}") from exc
    if "X" not in rendered or "1" not in rendered:
        raise PriceFormatError("price_format должен содержать и {name}, и {price}")
    return template


def parse_position(line: str) -> tuple[str, int] | None:
    """Разобрать товарную строку в (название, закупочная цена).

    None означает, что строка не товарная: заголовок, разделитель, примечание.
    """
    match = _PRICE_LINE_RE.match(line)
    if not match:
        return None

    price = int(match.group("price"))
    if price < _MIN_PRICE:
        return None

    return _NAME_TAIL_RE.sub("", match.group("head")).strip(), price


def rewrite_line(
    line: str,
    tiers: Sequence[MarkupTier],
    round_to: int = 0,
    price_format: str = DEFAULT_PRICE_FORMAT,
) -> str:
    """Заменить цену в строке на цену с наценкой; прочие строки вернуть как есть."""
    parsed = parse_position(line)
    if parsed is None:
        return line

    name, price = parsed
    return price_format.format(name=name, price=apply_markup(price, tiers, round_to))


def rewrite_prices(
    lines: Sequence[str],
    tiers: Sequence[MarkupTier],
    round_to: int = 0,
    price_format: str = DEFAULT_PRICE_FORMAT,
) -> list[str]:
    """Применить наценку ко всем строкам блока."""
    return [rewrite_line(line, tiers, round_to, price_format) for line in lines]


def count_price_lines(lines: Sequence[str]) -> int:
    """Сколько строк распознано как товарные — для логов и проверок."""
    return sum(1 for line in lines if parse_position(line) is not None)


def split_blocks(lines: Sequence[str]) -> list[list[str]]:
    """Разбить строки на смысловые блоки по пустым строкам."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _block_len(block: Sequence[str]) -> int:
    """Длина блока в символах вместе с разделяющей пустой строкой."""
    return sum(len(line) + 1 for line in block) + 1


def _split_oversized(block: list[str], capacity: int) -> list[list[str]]:
    """Разрезать блок, который сам по себе не влезает в сообщение."""
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for line in block:
        line_len = len(line) + 1
        if current and current_len + line_len > capacity:
            chunks.append(current)
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append(current)
    return chunks


def distribute(
    blocks: Sequence[Sequence[str]],
    slots: int,
    capacity: int,
) -> list[list[str]]:
    """Разложить блоки по слотам, выравнивая объём.

    Возвращает не меньше `slots` частей; если контент не помещается,
    добавляются дополнительные части — вызывающий код решает, что с ними делать.
    """
    if slots < 1:
        raise ValueError("slots должен быть >= 1")

    queue: list[list[str]] = []
    for block in blocks:
        block = list(block)
        if _block_len(block) > capacity:
            queue.extend(_split_oversized(block, capacity))
        else:
            queue.append(block)

    parts: list[list[str]] = []
    while queue or len(parts) < slots:
        slots_left = max(1, slots - len(parts))
        remaining = sum(_block_len(block) for block in queue)
        budget = math.ceil(remaining / slots_left) if slots_left else capacity

        current: list[str] = []
        current_len = 0
        while queue:
            block = queue[0]
            block_len = _block_len(block)
            if current and current_len + block_len > capacity:
                break
            if current and current_len >= budget and len(parts) + 1 < slots:
                break
            queue.pop(0)
            if current:
                current.append("")
            current.extend(block)
            current_len += block_len

        parts.append(current)
        if not queue and len(parts) >= slots:
            break

    return parts


def render_message(title: str, part_no: int, total_parts: int, lines: Sequence[str]) -> str:
    """Собрать HTML-текст одного сообщения категории."""
    suffix = f" (часть {part_no}/{total_parts})" if total_parts > 1 else ""
    header = f"\U0001F4E6 <b>{html.escape(title + suffix)}</b>"
    body = "\n".join(html.escape(line) for line in lines)
    return f"{header}\n\n{body}" if body else header


def build_messages(
    title: str,
    lines: Sequence[str],
    slots: int,
    tiers: Sequence[MarkupTier],
    round_to: int = 0,
    max_len: int = TELEGRAM_MAX_LEN,
    price_format: str = DEFAULT_PRICE_FORMAT,
) -> list[str]:
    """Полный конвейер: наценка -> разбиение на части -> HTML-сообщения."""
    priced = rewrite_prices(lines, tiers, round_to, price_format)
    blocks = split_blocks(priced)

    # Запас под заголовок с максимально возможным номером части.
    overhead = len(render_message(title, slots + 9, slots + 9, []))
    capacity = max_len - overhead - 2
    if capacity <= 0:
        raise ValueError(f"Заголовок категории '{title}' не оставляет места под контент")

    parts = distribute(blocks, slots, capacity)
    total = len(parts)
    return [render_message(title, index + 1, total, part) for index, part in enumerate(parts)]
