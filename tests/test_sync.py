from pathlib import Path

import pytest

from catalog import Category, CategoryPart
from config import Config
from markup import parse_tiers
from state import CategorySlot, State
from sync import build_excel, content_hash, is_allowed, planned_keys, render_category

TIERS = parse_tiers([{"up_to": 80000, "add": 5000}, {"up_to": None, "add": 13000}])


def make_config(**overrides) -> Config:
    base = dict(
        bot_token="test",
        source_channel="src",
        target_chat_id="-1002150017620",
        target_channel=None,
        tiers=TIERS,
        round_to_nearest=0,
        price_format="{name} — {price} ₽",
        check_interval=3600,
        max_scan_pages=8,
        categories=(),
        deny_categories=(),
        allow_create=False,
        disable_notification=True,
        nav_enabled=True,
        nav_text="ВЫБЕРИТЕ",
        nav_columns=3,
        nav_row_width=30,
        nav_pin=True,
        nav_button_style="default",
        order_button=None,
        excel_enabled=False,
        excel_publish=False,
        excel_output_dir=Path("_excel"),
        excel_filename="price_{date}.xlsx",
        excel_button_text="Прайс EXCEL",
        excel_button_style="success",
        proxy=None,
    )
    base.update(overrides)
    return Config(**base)


def make_category(title: str, lines: list[str]) -> Category:
    part = CategoryPart(message_id=1, part_no=1, declared_total=1, lines=tuple(lines))
    return Category(title=title, key=title.casefold(), parts=[part])


def test_render_category_fills_all_slots():
    category = make_category("Samsung", [f"Item {i} - {10000 + i}" for i in range(60)])
    slot = CategorySlot(title="Samsung", message_ids=[1, 2, 3])
    parts, dropped = render_category(category, slot, make_config())
    assert len(parts) == 3
    assert dropped == 0


def test_render_category_truncates_when_creation_disabled():
    lines = [f"Item {i} - {10000 + i}" for i in range(600)]
    category = make_category("Samsung", lines)
    slot = CategorySlot(title="Samsung", message_ids=[1])
    parts, dropped = render_category(category, slot, make_config())
    assert len(parts) == 1
    assert dropped > 0
    assert "уточняйте" in parts[0]


def test_render_category_overflows_when_creation_allowed():
    lines = [f"Item {i} - {10000 + i}" for i in range(600)]
    category = make_category("Samsung", lines)
    slot = CategorySlot(title="Samsung", message_ids=[1])
    parts, dropped = render_category(category, slot, make_config(allow_create=True))
    assert len(parts) > 1
    assert dropped == 0


def test_render_category_handles_empty_slot_list():
    category = make_category("Google", ["A - 1000"])
    parts, dropped = render_category(category, CategorySlot(title="Google"), make_config())
    assert len(parts) == 1 and dropped == 0


@pytest.mark.parametrize(
    "key,cfg,expected",
    [
        ("samsung", make_config(), True),
        ("samsung", make_config(deny_categories=("Samsung",)), False),
        ("samsung", make_config(categories=("Google",)), False),
        ("google", make_config(categories=("Google",)), True),
        ("iphone 11 / 12", make_config(deny_categories=("iPhone 11 \\ 12",)), False),
    ],
)
def test_is_allowed(key, cfg, expected):
    assert is_allowed(key, cfg) is expected


def test_content_hash_is_order_sensitive():
    assert content_hash(["a", "b"]) != content_hash(["b", "a"])
    assert content_hash(["a", "b"]) == content_hash(["a", "b"])


def test_planned_keys_follows_config_order():
    cfg = make_config(categories=("iPhone 17 Pro", "Google", "Samsung"))
    assert planned_keys(cfg, State()) == ["iphone 17 pro", "google", "samsung"]


def test_planned_keys_drops_denied_and_duplicates():
    cfg = make_config(categories=("Google", "Google", "Samsung"), deny_categories=("Samsung",))
    assert planned_keys(cfg, State()) == ["google"]


def test_planned_keys_falls_back_to_state():
    state = State(slots={"google": CategorySlot(title="Google", message_ids=[1])})
    assert planned_keys(make_config(), state) == ["google"]


def test_render_category_uses_source_parts_for_new_category():
    part_a = CategoryPart(message_id=1, part_no=1, declared_total=2, lines=("A - 10000",))
    part_b = CategoryPart(message_id=2, part_no=2, declared_total=2, lines=("B - 20000",))
    category = Category(title="Samsung", key="samsung", parts=[part_a, part_b])
    parts, _ = render_category(category, CategorySlot(title="Samsung"), make_config())
    assert len(parts) == 2


def test_build_excel_writes_file_and_skips_when_disabled(tmp_path):
    category = make_category("Google", ["Pixel 10 256GB - 60000"])
    categories = {"google": category}
    state = State()

    off = make_config(categories=("Google",), excel_output_dir=tmp_path)
    assert build_excel(off, state, categories) is None
    assert not list(tmp_path.iterdir())

    on = make_config(
        categories=("Google",), excel_enabled=True,
        excel_output_dir=tmp_path, excel_filename="p_{date}.xlsx",
    )
    payload, filename, rows = build_excel(on, state, categories)
    assert (tmp_path / filename).read_bytes() == payload
    assert [(r.category, r.price) for r in rows] == [("Google", 65000)]


def test_build_excel_returns_none_without_positions(tmp_path):
    cfg = make_config(categories=("Google",), excel_enabled=True, excel_output_dir=tmp_path)
    empty = make_category("Google", ["просто текст"])
    assert build_excel(cfg, State(), {"google": empty}) is None
