"""Перераскладка категорий по уже существующим постам канала.

Telegram не переставляет сообщения, а свои посты старше 48 часов бот удалить
не может. Когда у канала меняется список категорий (добавились серии Samsung,
ушли старые айфоны), новые категории иначе встали бы в конец канала, а
выбывшие оставили бы дыры. Посты — просто контейнеры, их можно переписать,
поэтому категории заново раскладываются по постам канала в порядке
конфига: первая категория — в самый ранний пост, и так далее. Навигация
и информационное сообщение получают то, что осталось, или создаются заново
в конце. Ссылки навигации пересобираются сами — они ведут на message_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from state import CategorySlot, State


@dataclass
class Relayout:
    """Итог перераскладки: новое состояние и что сделать с бывшей навигацией."""

    state: State
    # Бывшая навигация стала прайсом — её нужно открепить, новая закрепится сама.
    unpin_message_id: int | None = None
    # Посты, которым не хватило категорий: так и останутся со старым содержимым.
    leftover_ids: list[int] = field(default_factory=list)


def relayout(
    state: State,
    keys: list[str],
    titles: dict[str, str],
    *,
    reuse_ids: Iterable[int] = (),
    parts_per_category: int = 1,
) -> Relayout:
    """Разложить категории `keys` по постам канала в порядке возрастания message_id.

    reuse_ids — посты канала, которые бот уже не ведёт (выбывшие категории),
    но которые ещё живы и годятся под новые. Все хеши сбрасываются: следующий
    прогон перепишет каждый пост.
    """
    old_nav = state.nav_message_id
    pool = sorted({
        *(mid for slot in state.slots.values() for mid in slot.message_ids),
        *(mid for mid in (state.info_message_id, old_nav) if mid),
        *reuse_ids,
    })

    slots: dict[str, CategorySlot] = {}
    for key in keys:
        taken, pool = pool[:parts_per_category], pool[parts_per_category:]
        slots[key] = CategorySlot(title=titles.get(key, key), message_ids=taken)

    info_id = pool.pop(0) if state.info_message_id and pool else None
    nav_id = pool.pop(0) if old_nav and pool else None

    new_state = State(
        slots=slots,
        nav_message_id=nav_id,
        excel_message_id=state.excel_message_id,
        excel_hash=state.excel_hash,
        info_message_id=info_id,
    )
    return Relayout(
        state=new_state,
        unpin_message_id=old_nav if old_nav and old_nav != nav_id else None,
        leftover_ids=pool,
    )
