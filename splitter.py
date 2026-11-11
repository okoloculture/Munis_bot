"""Разбиение одной категории опта на несколько категорий канала.

Опт публикует Samsung одним большим блоком, а покупатель ищет по сериям,
как у Apple: Galaxy S, Galaxy A, Galaxy Z… Правила задаются в конфиге
канала ключом split_categories: строка уходит в первую серию, чей шаблон
совпал с её началом. Получившиеся категории дальше живут как обычные —
со своим постом и своей кнопкой в навигации.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from catalog import Category, CategoryPart, normalize_key

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SplitTarget:
    """Категория канала и шаблон строк опта, которые в неё попадают."""

    title: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class CategorySplit:
    """Правило разбиения: категория опта -> упорядоченные серии."""

    source: str
    targets: tuple[SplitTarget, ...]


class SplitConfigError(ValueError):
    """Правило разбиения задано некорректно."""


def parse_splits(raw: object) -> tuple[CategorySplit, ...]:
    """Разобрать split_categories: {Категория опта: [{title, pattern}, …]}."""
    if not raw:
        return ()
    if not isinstance(raw, dict):
        raise SplitConfigError("'split_categories' должен быть словарём")

    splits = []
    for source, targets in raw.items():
        if not isinstance(targets, list) or not targets:
            raise SplitConfigError(f"split_categories.{source}: нужен непустой список серий")
        parsed = []
        for target in targets:
            title = target.get("title") if isinstance(target, dict) else None
            pattern = target.get("pattern") if isinstance(target, dict) else None
            if not isinstance(title, str) or not title.strip():
                raise SplitConfigError(f"split_categories.{source}: у серии нужен 'title'")
            if not isinstance(pattern, str) or not pattern:
                raise SplitConfigError(f"split_categories.{source}.{title}: нужен 'pattern'")
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise SplitConfigError(
                    f"split_categories.{source}.{title}: некорректный шаблон: {exc}"
                ) from exc
            parsed.append(SplitTarget(title=title.strip(), pattern=compiled))
        splits.append(CategorySplit(source=str(source), targets=tuple(parsed)))
    return tuple(splits)


def _category(title: str, lines: list[str]) -> Category:
    while lines and not lines[-1].strip():
        lines.pop()
    part = CategoryPart(message_id=0, part_no=1, declared_total=1, lines=tuple(lines))
    return Category(title=title, key=normalize_key(title), parts=[part])


def split_category(category: Category, split: CategorySplit) -> list[Category]:
    """Разложить строки категории по сериям, сохраняя пустые строки между блоками.

    Строки, не подошедшие ни к одной серии, остаются в категории с исходным
    названием: если она есть в списке категорий канала, они не потеряются.
    """
    buckets: dict[str, list[str]] = {target.title: [] for target in split.targets}
    rest: list[str] = []
    pending_blank: set[str] = set()

    for line in category.lines:
        if not line.strip():
            pending_blank = set(buckets) | {""}
            continue
        target = next((t for t in split.targets if t.pattern.match(line.strip())), None)
        name = target.title if target else ""
        bucket = buckets[name] if target else rest
        if bucket and name in pending_blank:
            bucket.append("")
        pending_blank.discard(name)
        bucket.append(line)

    if rest:
        log.warning(
            "'%s': %d строк не подошли ни к одной серии — остаются в '%s'",
            category.title, sum(1 for line in rest if line.strip()), category.title,
        )

    result = [_category(title, lines) for title, lines in buckets.items()]
    if rest:
        result.append(_category(category.title, rest))
    return result


def apply_splits(
    categories: dict[str, Category], splits: tuple[CategorySplit, ...],
) -> dict[str, Category]:
    """Заменить разбиваемые категории их сериями; остальное вернуть как есть."""
    if not splits:
        return categories
    by_key = {normalize_key(split.source): split for split in splits}
    result: dict[str, Category] = {}
    for key, category in categories.items():
        split = by_key.get(key)
        if split is None:
            result[key] = category
            continue
        for part in split_category(category, split):
            result[part.key] = part
    return result
