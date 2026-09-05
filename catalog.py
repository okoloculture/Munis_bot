"""Сборка логических категорий прайса из сообщений канала.

Источник публикует каталог блоком сообщений вида «📦 Samsung (часть 3/8)».
Блок периодически перепубликуется целиком, поэтому message_id непостоянны —
категории определяются по заголовку, а не по захардкоженным id.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from tme_scraper import ChannelMessage

log = logging.getLogger(__name__)

CATEGORY_MARKER = "\U0001F4E6"  # 📦
_ZERO_WIDTH = "​‌‍﻿"

_HEADER_RE = re.compile(rf"^\s*{CATEGORY_MARKER}\s*(?P<title>.+?)\s*$")
_PART_RE = re.compile(r"\s*\(\s*часть\s*(?P<part>\d+)\s*/\s*(?P<total>\d+)\s*\)\s*$", re.IGNORECASE)

# Части одной категории публикуются подряд; всё, что отстоит от свежайшей части
# дальше этого окна, считается предыдущей (устаревшей) публикацией каталога.
_STALE_ID_WINDOW = 300


@dataclass(frozen=True)
class CategoryPart:
    """Одно сообщение-часть категории."""

    message_id: int
    part_no: int
    declared_total: int
    lines: tuple[str, ...]


@dataclass
class Category:
    """Логическая категория, склеенная из своих частей."""

    title: str
    key: str
    parts: list[CategoryPart] = field(default_factory=list)

    @property
    def message_ids(self) -> list[int]:
        return [part.message_id for part in self.parts]

    @property
    def lines(self) -> list[str]:
        """Все товарные строки категории в исходном порядке."""
        merged: list[str] = []
        for part in self.parts:
            if merged and part.lines:
                merged.append("")
            merged.extend(part.lines)
        return _strip_edge_blanks(merged)


def normalize_key(title: str) -> str:
    """Ключ для сопоставления категорий между каналами.

    Нечувствителен к регистру, кратности пробелов, виду слэша и невидимым символам.
    """
    cleaned = title.translate({ord(ch): None for ch in _ZERO_WIDTH})
    cleaned = cleaned.replace("\\", "/")
    cleaned = re.sub(r"\s*/\s*", " / ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().casefold()


def parse_header(line: str) -> tuple[str, int, int] | None:
    """Разобрать строку-заголовок: вернуть (заголовок без части, номер части, всего частей)."""
    stripped = line.translate({ord(ch): None for ch in _ZERO_WIDTH}).strip()
    match = _HEADER_RE.match(stripped)
    if not match:
        return None

    title = match.group("title").strip()
    part_match = _PART_RE.search(title)
    if part_match:
        base = title[: part_match.start()].strip()
        return base, int(part_match.group("part")), int(part_match.group("total"))
    return title, 1, 1


def _strip_edge_blanks(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _message_to_part(message: ChannelMessage) -> tuple[str, CategoryPart] | None:
    """Превратить сообщение в часть категории, если это сообщение-прайс."""
    raw_lines = message.text.split("\n")
    if not raw_lines:
        return None

    parsed = parse_header(raw_lines[0])
    if parsed is None:
        return None

    title, part_no, declared_total = parsed
    body = _strip_edge_blanks([line.rstrip() for line in raw_lines[1:]])
    if not body:
        return None

    part = CategoryPart(
        message_id=message.message_id,
        part_no=part_no,
        declared_total=declared_total,
        lines=tuple(body),
    )
    return title, part


def build_categories(messages: list[ChannelMessage]) -> dict[str, Category]:
    """Собрать актуальные категории: по одной свежей версии каждой части."""
    buckets: dict[str, list[tuple[str, CategoryPart]]] = {}
    for message in messages:
        parsed = _message_to_part(message)
        if parsed is None:
            continue
        title, part = parsed
        buckets.setdefault(normalize_key(title), []).append((title, part))

    categories: dict[str, Category] = {}
    for key, entries in buckets.items():
        newest_id = max(part.message_id for _, part in entries)
        fresh = [(t, p) for t, p in entries if newest_id - p.message_id <= _STALE_ID_WINDOW]

        by_part: dict[int, tuple[str, CategoryPart]] = {}
        for title, part in fresh:
            current = by_part.get(part.part_no)
            if current is None or part.message_id > current[1].message_id:
                by_part[part.part_no] = (title, part)

        ordered = [by_part[no] for no in sorted(by_part)]
        title = ordered[-1][0]
        parts = [part for _, part in ordered]

        declared = parts[-1].declared_total
        if declared != len(parts):
            log.warning(
                "Категория '%s': найдено %d частей из заявленных %d — публикую то, что есть",
                title, len(parts), declared,
            )

        categories[key] = Category(title=title, key=key, parts=parts)

    return categories
