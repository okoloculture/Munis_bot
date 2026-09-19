"""Ступенчатая наценка в абсолютных рублях."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class MarkupTier:
    """Одна ступень наценки.

    up_to — верхняя граница закупочной цены включительно; None означает
    «всё остальное» и допустим только у последней ступени.

    Ступень задаётся ровно одним способом: add — прибавка в рублях,
    pct — процент от закупочной цены.
    """

    up_to: int | None
    add: int = 0
    pct: float = 0.0


class MarkupConfigError(ValueError):
    """Ступени наценки заданы некорректно."""


def parse_tiers(raw: Iterable[dict]) -> tuple[MarkupTier, ...]:
    """Собрать и провалидировать ступени из конфига."""
    tiers: list[MarkupTier] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise MarkupConfigError(f"Ступень #{index} должна быть словарём, получено {item!r}")
        has_add, has_pct = "add" in item, "pct" in item
        if has_add == has_pct:
            raise MarkupConfigError(
                f"Ступень #{index}: нужно ровно одно поле — 'add' (рубли) или 'pct' (проценты)"
            )

        add, pct = item.get("add", 0), item.get("pct", 0.0)
        up_to = item.get("up_to")
        if has_add and (not isinstance(add, int) or isinstance(add, bool) or add < 0):
            raise MarkupConfigError(f"Ступень #{index}: 'add' должен быть неотрицательным int")
        if has_pct and (not isinstance(pct, (int, float)) or isinstance(pct, bool) or pct < 0):
            raise MarkupConfigError(f"Ступень #{index}: 'pct' должен быть неотрицательным числом")
        if up_to is not None and (not isinstance(up_to, int) or isinstance(up_to, bool) or up_to <= 0):
            raise MarkupConfigError(f"Ступень #{index}: 'up_to' должен быть положительным int или null")
        tiers.append(MarkupTier(up_to=up_to, add=int(add), pct=float(pct)))

    if not tiers:
        raise MarkupConfigError("Список ступеней наценки пуст")
    if tiers[-1].up_to is not None:
        raise MarkupConfigError("Последняя ступень должна иметь 'up_to: null' (остальное)")
    if any(tier.up_to is None for tier in tiers[:-1]):
        raise MarkupConfigError("'up_to: null' допустим только у последней ступени")

    bounds = [tier.up_to for tier in tiers[:-1]]
    if bounds != sorted(bounds) or len(set(bounds)) != len(bounds):
        raise MarkupConfigError("Границы ступеней должны строго возрастать")

    return tuple(tiers)


def tier_for(price: int, tiers: Sequence[MarkupTier]) -> MarkupTier:
    """Найти ступень, под которую попадает закупочная цена."""
    for tier in tiers:
        if tier.up_to is None or price <= tier.up_to:
            return tier
    return tiers[-1]


def markup_for(price: int, tiers: Sequence[MarkupTier]) -> int:
    """Наценка в рублях для закупочной цены; процентная приводится к рублям."""
    tier = tier_for(price, tiers)
    if tier.pct:
        # Округляем до рубля здесь, чтобы наценка была одним и тем же числом
        # и в расчёте цены, и в отчётах по ступеням.
        return round(price * tier.pct / 100)
    return tier.add


def apply_markup(price: int, tiers: Sequence[MarkupTier], round_to: int = 0) -> int:
    """Прибавить наценку и при необходимости округлить вверх."""
    result = price + markup_for(price, tiers)
    if round_to > 0:
        result = math.ceil(result / round_to) * round_to
    return result
