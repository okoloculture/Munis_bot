"""Сборка постов категорий в виде таблиц Rich Messages (Bot API 10.1+).

Rich-сообщение принимает до 32768 символов текста — в восемь раз больше
обычного, поэтому категория почти всегда помещается в один пост. Таблица
в две колонки: название и цена с наценкой.

Сдвоенная категория опта («iPhone 17e \\ 17») раскладывается на отдельные
таблицы по моделям, чтобы покупатель видел, где кончаются 17e и начинаются 17.
Модель, которой сейчас нет в опте, получает таблицу «Цена по запросу» —
пустая графа выглядит как «здесь не продают».
"""

from __future__ import annotations

import html
from typing import Sequence

from markup import MarkupTier, apply_markup
from names import tidy_name
from renderer import distribute, parse_position, split_blocks

RICH_MAX_TEXT = 32768
# Лимит считается по тексту без разметки; запас — под заголовки, «₽» и
# пересчитанные цены, которые бывают на разряд длиннее закупочных.
RICH_CAPACITY = 30000
PRICE_HEADER = "Цена"
EMPTY_TEXT = "Цена по запросу"
# Так опт помечает пустую категорию; покупателю это читается как «нет и не будет».
_EMPTY_MARKERS = ("товары не найдены",)
# Модель ищется среди первых слов строки: у макбуков впереди заводской код.
_MODEL_SCAN_WORDS = 3


def category_models(title: str) -> tuple[str, list[tuple[str, str]]]:
    """Разобрать заголовок сдвоенной категории на модели.

    «iPhone 17e \\ 17» -> ("iPhone", [("17e", "iPhone 17e"), ("17", "iPhone 17")]).
    Возвращает (общая часть названия, [(ключ, название модели)]); у обычной
    категории список пуст.
    """
    tokens = [token.strip() for token in title.split("\\") if token.strip()]
    if len(tokens) < 2:
        return "", []
    first = tokens[0].split()
    base = " ".join(first[:-1])
    models = [(first[-1], tokens[0])]
    for token in tokens[1:]:
        full = f"{base} {token}" if base and " " not in token else token
        models.append((token, full))
    return base, models


def model_of(line: str, base: str, keys: Sequence[str]) -> str | None:
    """Ключ модели, к которой относится строка, или None."""
    words = line.split()
    if base and [w.casefold() for w in words[:len(base.split())]] == base.casefold().split():
        words = words[len(base.split()):]
    folded = [word.casefold() for word in words]
    by_length = sorted(keys, key=lambda key: -len(key.split()))
    for start in range(min(_MODEL_SCAN_WORDS, len(folded))):
        for key in by_length:
            key_words = key.casefold().split()
            if folded[start:start + len(key_words)] == key_words:
                return key
    return None


def _is_empty_marker(line: str) -> bool:
    return line.strip().casefold() in _EMPTY_MARKERS


def _row(title: str, line: str, tiers: Sequence[MarkupTier], round_to: int, tidy: bool) -> str:
    parsed = parse_position(line)
    if parsed is None:
        # Строка без цены (подзаголовок, примечание) — на всю ширину таблицы.
        return f'<tr><td colspan="2"><b>{html.escape(line.strip())}</b></td></tr>'
    name, price = parsed
    if tidy:
        name = tidy_name(title, name)
    retail = apply_markup(price, tiers, round_to)
    return f"<tr><td>{html.escape(name)}</td><td>{retail} ₽</td></tr>"


def _table(header: str, rows: Sequence[str]) -> str:
    body = rows or [f'<tr><td colspan="2">{EMPTY_TEXT}</td></tr>']
    head = f"<table bordered><tr><th>{html.escape(header)}</th><th>{PRICE_HEADER}</th></tr>"
    return "\n".join([head, *body]) + "</table>"


def _group_by_model(lines: Sequence[str], base: str, models: Sequence[tuple[str, str]]) -> dict[str, list[str]]:
    keys = [key for key, _ in models]
    groups: dict[str, list[str]] = {key: [] for key in keys}
    current = keys[0]
    for line in lines:
        if not line.strip() or _is_empty_marker(line):
            continue
        # Строка без узнаваемой модели продолжает предыдущую: опт пишет модели блоками.
        current = model_of(line, base, keys) or current
        groups[current].append(line)
    return groups


def render_rich_message(
    title: str,
    part_no: int,
    total_parts: int,
    lines: Sequence[str],
    tiers: Sequence[MarkupTier],
    round_to: int = 0,
    *,
    tidy: bool = False,
    placeholders: frozenset[str] = frozenset(),
) -> str:
    """Собрать HTML одного rich-поста категории.

    placeholders — модели сдвоенной категории, которых нет во всей категории:
    для них рисуется таблица «Цена по запросу».
    """
    suffix = f" (часть {part_no}/{total_parts})" if total_parts > 1 else ""
    base, models = category_models(title)

    if not models:
        rows = [
            _row(title, line, tiers, round_to, tidy)
            for line in lines if line.strip() and not _is_empty_marker(line)
        ]
        return _table(title + suffix, rows)

    groups = _group_by_model(lines, base, models)
    tables = []
    for key, name in models:
        if tidy:
            # Заголовок таблицы в том же виде, что и строки под ним: «Apple Watch SE».
            name = tidy_name(title, name)
        if groups[key]:
            rows = [_row(title, line, tiers, round_to, tidy) for line in groups[key]]
            tables.append(_table(name + suffix, rows))
        elif key in placeholders:
            tables.append(_table(name, []))
    return "\n".join(tables) if tables else _table(title + suffix, [])


def build_rich_messages(
    title: str,
    lines: Sequence[str],
    slots: int,
    tiers: Sequence[MarkupTier],
    round_to: int = 0,
    capacity: int = RICH_CAPACITY,
    *,
    tidy: bool = False,
) -> list[str]:
    """Разложить строки категории по `slots` rich-постам; не влезло — частей больше."""
    parts = distribute(split_blocks(lines), slots, capacity)
    total = len(parts)

    base, models = category_models(title)
    present = _group_by_model(lines, base, models) if models else {}
    missing = frozenset(key for key, found in present.items() if not found)

    return [
        render_rich_message(
            title, index + 1, total, part, tiers, round_to,
            tidy=tidy,
            # Заглушки — один раз, в последней части, чтобы не дублировать.
            placeholders=missing if index == total - 1 else frozenset(),
        )
        for index, part in enumerate(parts)
    ]
