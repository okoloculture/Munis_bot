"""Названия позиций для клиента: тип техники в начале, лишняя спецификация убрана.

Опт пишет так, как удобно оптовику: у айфонов нет слова iPhone («17e 256GB …»),
у макбуков впереди заводской код и полная конфигурация ядер
(«MHFD4 Neo Citrus A18 Pro (6/5/8/256)»). Розничному покупателю нужно
«MacBook Neo Citrus A18 Pro 8/256 (MHFD4)»: что это, какая память, а код —
в конце, для менеджера. Включается ключом tidy_names в конфиге канала.
"""

from __future__ import annotations

import re

# Заводской код Apple в начале строки и конфигурация в скобках в конце:
# CPU/GPU/RAM/SSD. Покупателю из неё нужны только память и накопитель.
_MAC_RE = re.compile(
    r"^(?P<code>[A-Z0-9]{5})\s+(?P<model>.+?)\s*"
    r"\((?:[^/()]+/){2}(?P<ram>[^/()]+)/(?P<ssd>[^/()]+)\)\s*$"
)

# Категория -> тип техники, который ставится в начало названия, если его там нет.
# У брендовых категорий (Samsung, Xiaomi, Google…) тип и так есть в строке.
_TYPE_BY_CATEGORY = (
    ("iphone", "iPhone"),
    ("macbook", "MacBook"),
    ("ipad", "iPad"),
    ("watch", "Apple Watch"),
)


def product_type(category_title: str) -> str | None:
    """Тип техники для категории или None, если добавлять нечего."""
    lowered = category_title.casefold()
    for marker, kind in _TYPE_BY_CATEGORY:
        if lowered.startswith(marker) or f" {marker}" in lowered:
            return kind
    return None


def _with_type(name: str, kind: str) -> str:
    # «Watch S11» уже говорит, что это часы: достраиваем до «Apple Watch S11»,
    # а не ставим тип второй раз.
    last_word = kind.split()[-1]
    if name.casefold().startswith(kind.casefold()):
        return name
    if name.casefold().startswith(last_word.casefold()):
        return f"{kind}{name[len(last_word):]}"
    return f"{kind} {name}"


def tidy_name(category_title: str, name: str) -> str:
    """Привести название позиции к виду «Тип Модель … Память (Код)»."""
    mac = _MAC_RE.match(name)
    if mac:
        name = f"{mac['model']} {mac['ram']}/{mac['ssd']} ({mac['code']})"

    kind = product_type(category_title)
    return _with_type(name, kind) if kind else name
