from pathlib import Path

import pytest

from catalog import Category, CategoryPart
from config import Config
from markup import parse_tiers
import sync
from bot_api import MESSAGE_GONE
from state import CategorySlot, State
from sync import (
    build_excel,
    ensure_info_is_after_prices,
    ensure_nav_is_last,
    content_hash,
    is_allowed,
    planned_keys,
    publish_category,
    publish_info,
    publish_nav,
    read_info_text,
    render_category,
)

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
        info_enabled=False,
        info_file=Path("info.html"),
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


def test_read_info_text_disabled_returns_none(tmp_path):
    path = tmp_path / "info.html"
    path.write_text("<b>Привет</b>", encoding="utf-8")
    assert read_info_text(make_config(info_file=path)) is None


def test_read_info_text_reads_and_strips(tmp_path):
    path = tmp_path / "info.html"
    path.write_text("\n<b>Привет</b>\nТекст\n\n", encoding="utf-8")
    cfg = make_config(info_enabled=True, info_file=path)
    assert read_info_text(cfg) == "<b>Привет</b>\nТекст"


def test_read_info_text_rejects_empty_and_oversized(tmp_path):
    empty = tmp_path / "empty.html"
    empty.write_text("   \n", encoding="utf-8")
    assert read_info_text(make_config(info_enabled=True, info_file=empty)) is None

    huge = tmp_path / "huge.html"
    huge.write_text("я" * 5000, encoding="utf-8")
    assert read_info_text(make_config(info_enabled=True, info_file=huge)) is None


def test_read_info_text_survives_missing_file(tmp_path):
    cfg = make_config(info_enabled=True, info_file=tmp_path / "нет.html")
    assert read_info_text(cfg) is None


def _state_with(slots: dict[str, list[int]], *, info: int | None = None,
                nav: int | None = None) -> State:
    return State(
        slots={k: CategorySlot(title=k, message_ids=v) for k, v in slots.items()},
        info_message_id=info, nav_message_id=nav,
    )


def test_ensure_info_after_prices_detects_new_posts_below():
    import asyncio

    class Api:
        def __init__(self): self.deleted = []
        async def delete_message(self, chat, mid):
            self.deleted.append(mid); return {}

    api = Api()
    state = _state_with({"a": [2, 3], "new": [50]}, info=48, nav=49)
    assert asyncio.run(ensure_info_is_after_prices(api, make_config(), state)) is True
    assert api.deleted == [48]
    assert state.info_message_id is None


def test_ensure_info_after_prices_noop_when_already_last():
    import asyncio
    state = _state_with({"a": [2, 3]}, info=48, nav=49)
    assert asyncio.run(ensure_info_is_after_prices(None, make_config(), state)) is False
    assert state.info_message_id == 48


def test_ensure_nav_is_last_triggers_on_any_message_below():
    import asyncio

    class Api:
        def __init__(self): self.deleted = []
        async def delete_message(self, chat, mid):
            self.deleted.append(mid); return {}

    api = Api()
    state = _state_with({"a": [2], "new": [50]}, info=51, nav=49)
    assert asyncio.run(ensure_nav_is_last(api, make_config(), state)) is True
    assert api.deleted == [49]
    assert state.nav_message_id is None


def test_ensure_nav_is_last_noop_when_lowest():
    import asyncio
    state = _state_with({"a": [2]}, info=48, nav=49)
    assert asyncio.run(ensure_nav_is_last(None, make_config(), state)) is False


class GoneApi:
    """Фейковый Bot API: сообщения из `gone` удалены из канала руками."""

    def __init__(self, gone: set[int], next_id: int = 100):
        self.gone = gone
        self.next_id = next_id
        self.edited: list[int] = []
        self.sent: list[int] = []

    async def edit_message_text(self, chat, mid, text, reply_markup=None):
        if mid in self.gone:
            return MESSAGE_GONE
        self.edited.append(mid)
        return {"message_id": mid}

    async def send_message(self, chat, text, disable_notification=True, reply_markup=None):
        mid = self.next_id
        self.next_id += 1
        self.sent.append(mid)
        return {"message_id": mid}

    async def pin_message(self, chat, mid):
        self.pinned = mid
        return {}

    async def unpin_message(self, chat, mid):
        self.unpinned = mid
        return {}


@pytest.fixture
def no_delays(monkeypatch):
    monkeypatch.setattr(sync, "EDIT_DELAY_SECONDS", 0)
    monkeypatch.setattr(sync, "CREATE_DELAY_SECONDS", 0)


def test_publish_category_folds_deleted_part_into_remaining(no_delays):
    import asyncio
    category = make_category("Huawei", [f"Item {i} - {10000 + i}" for i in range(10)])
    slot = CategorySlot(title="Huawei", message_ids=[4, 76])
    api = GoneApi(gone={76})

    assert asyncio.run(publish_category(api, make_config(allow_create=True), category, slot, State())) is True
    assert slot.message_ids == [4]
    assert api.sent == []
    assert slot.content_hash is not None


def test_publish_category_recreates_deleted_part_when_it_does_not_fit(no_delays):
    import asyncio
    category = make_category("Samsung", [f"Item number {i} - {10000 + i}" for i in range(300)])
    slot = CategorySlot(title="Samsung", message_ids=[12, 13])
    api = GoneApi(gone={13})

    assert asyncio.run(publish_category(api, make_config(allow_create=True), category, slot, State())) is True
    assert slot.message_ids == [12, 100]
    assert api.sent == [100]


def test_publish_category_drops_all_deleted_parts(no_delays):
    import asyncio
    category = make_category("Honor", ["Item - 10000"])
    slot = CategorySlot(title="Honor", message_ids=[3, 4])
    api = GoneApi(gone={3, 4})

    assert asyncio.run(publish_category(api, make_config(allow_create=True), category, slot, State())) is True
    assert slot.message_ids == [100]


def test_publish_info_recreates_deleted_message(tmp_path):
    import asyncio
    info = tmp_path / "info.html"
    info.write_text("Привет", encoding="utf-8")
    cfg = make_config(info_enabled=True, info_file=info)
    state = _state_with({}, info=77)
    state.info_hash = "stale"
    api = GoneApi(gone={77})

    assert asyncio.run(publish_info(api, cfg, state)) is True
    assert state.info_message_id == 100


def test_publish_nav_recreates_deleted_message():
    import asyncio
    state = _state_with({"a": [2]}, nav=78)
    state.nav_hash = "stale"
    api = GoneApi(gone={78})

    assert asyncio.run(publish_nav(api, make_config(categories=("a",)), state)) is True
    assert state.nav_message_id == 100


def test_new_price_part_takes_info_slot_instead_of_landing_below_nav(no_delays):
    import asyncio
    category = make_category("Samsung", [f"Item number {i} - {10000 + i}" for i in range(300)])
    slot = CategorySlot(title="Samsung", message_ids=[12, 13])
    state = _state_with({"Samsung": [12, 13]}, info=77, nav=78)
    state.info_hash = "info"
    api = GoneApi(gone={13})

    assert asyncio.run(publish_category(api, make_config(allow_create=True), category, slot, state)) is True
    assert slot.message_ids == [12, 77]
    assert api.sent == []
    assert state.info_message_id is None and state.info_hash is None
    assert state.nav_message_id == 78


def test_info_takes_nav_slot_and_nav_goes_to_the_end(tmp_path):
    import asyncio
    info = tmp_path / "info.html"
    info.write_text("Привет", encoding="utf-8")
    cfg = make_config(info_enabled=True, info_file=info, categories=("a",))
    state = _state_with({"a": [2, 77]}, nav=78)
    state.nav_hash = "nav"
    api = GoneApi(gone=set())

    assert asyncio.run(publish_info(api, cfg, state)) is True
    assert state.info_message_id == 78
    assert state.nav_message_id is None
    assert api.unpinned == 78

    assert asyncio.run(publish_nav(api, cfg, state)) is True
    assert state.nav_message_id == 100
    assert api.pinned == 100


def test_place_message_skips_deleted_service_post():
    import asyncio
    state = _state_with({}, info=77, nav=78)
    api = GoneApi(gone={77})

    mid = asyncio.run(sync.place_message(
        api, make_config(), state, "text", reply_markup=None, below=("info", "nav"),
    ))
    assert mid == 78
    assert state.info_message_id is None and state.nav_message_id is None


def test_place_message_sends_new_when_no_service_posts():
    import asyncio
    api = GoneApi(gone=set())
    mid = asyncio.run(sync.place_message(
        api, make_config(), State(), "text", reply_markup=None, below=("info", "nav"),
    ))
    assert mid == 100
    assert api.sent == [100]


class RichApi(GoneApi):
    """Фейковый Bot API, который различает обычные и rich-вызовы."""

    def __init__(self, gone: set[int] = frozenset(), next_id: int = 100):
        super().__init__(set(gone), next_id)
        self.rich_edited: list[int] = []
        self.rich_sent: list[int] = []

    async def edit_rich_message(self, chat, mid, html, reply_markup=None, photos=None):
        if mid in self.gone:
            return MESSAGE_GONE
        self.rich_edited.append(mid)
        return {"message_id": mid}

    async def send_rich_message(self, chat, html, disable_notification=True, reply_markup=None, photos=None):
        mid = self.next_id
        self.next_id += 1
        self.rich_sent.append(mid)
        return {"message_id": mid}


def test_rich_category_gets_one_post_regardless_of_source_parts(no_delays):
    import asyncio
    parts = [
        CategoryPart(message_id=i, part_no=i, declared_total=8,
                     lines=tuple(f"Item {i}.{j} - {10000 + j}" for j in range(30)))
        for i in range(1, 9)
    ]
    category = Category(title="Samsung", key="samsung", parts=parts)
    slot = CategorySlot(title="Samsung")
    api = RichApi()
    cfg = make_config(allow_create=True, rich_messages=True)

    assert asyncio.run(publish_category(api, cfg, category, slot, State())) is True
    assert api.rich_sent == [100]
    assert api.sent == []
    assert slot.message_ids == [100]


def test_rich_category_is_edited_with_rich_markup(no_delays):
    import asyncio
    category = make_category("AirPods", ["AirPods 4 - 8300"])
    slot = CategorySlot(title="AirPods", message_ids=[20])
    api = RichApi()

    assert asyncio.run(publish_category(api, make_config(rich_messages=True), category, slot, State())) is True
    assert api.rich_edited == [20]
    assert api.edited == []


def test_rich_new_part_takes_plain_info_post(no_delays):
    import asyncio
    category = make_category("Dyson", ["V11 Iron Red - 39100"])
    slot = CategorySlot(title="Dyson")
    state = _state_with({}, info=77, nav=78)
    api = RichApi()
    cfg = make_config(allow_create=True, rich_messages=True)

    assert asyncio.run(publish_category(api, cfg, category, slot, state)) is True
    assert slot.message_ids == [77]
    assert api.rich_edited == [77]
    assert state.info_message_id is None
