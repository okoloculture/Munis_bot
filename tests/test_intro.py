import asyncio

import pytest

import sync
from bot_api import MESSAGE_GONE
from intro import INTRO_KEY_PREFIX, IntroConfigError, IntroPost, load_intro, parse_intro_posts
from state import State
from sync import publish_intro, publish_nav
from tests.test_sync import make_config


@pytest.fixture
def post(tmp_path):
    html_file = tmp_path / "welcome.html"
    html_file.write_text("<p>Привет</p>\n", encoding="utf-8")
    photo = tmp_path / "welcome.jpg"
    photo.write_bytes(b"jpeg")
    return IntroPost(title="Welcome", html_file=html_file, photo_file=photo)


class IntroApi:
    def __init__(self, gone: set[int] = frozenset()):
        self.gone = set(gone)
        self.next_id = 100
        self.calls: list[tuple] = []

    async def edit_rich_message(self, chat, mid, html, reply_markup=None, photos=None):
        self.calls.append(("edit", mid, html, photos))
        return MESSAGE_GONE if mid in self.gone else {"message_id": mid}

    async def send_rich_message(self, chat, html, disable_notification=True, reply_markup=None, photos=None):
        self.calls.append(("send", self.next_id, html, photos))
        self.next_id += 1
        return {"message_id": self.next_id - 1}

    async def edit_message_text(self, chat, mid, text, reply_markup=None):
        return {"message_id": mid}

    async def pin_message(self, chat, mid):
        return {}

    async def unpin_message(self, chat, mid):
        return {}


@pytest.fixture(autouse=True)
def no_delays(monkeypatch):
    monkeypatch.setattr(sync, "EDIT_DELAY_SECONDS", 0)
    monkeypatch.setattr(sync, "CREATE_DELAY_SECONDS", 0)


def test_load_intro_puts_photo_above_text(post):
    html_text, photos, digest = load_intro(post)
    assert html_text.startswith('<img src="tg://photo?id=photo"/>')
    assert html_text.endswith("<p>Привет</p>")
    assert photos == {"photo": b"jpeg"}
    assert digest


def test_intro_hash_changes_with_photo(post):
    before = load_intro(post)[2]
    post.photo_file.write_bytes(b"other")
    assert load_intro(post)[2] != before


def test_parse_intro_posts_checks_files(tmp_path):
    with pytest.raises(IntroConfigError):
        parse_intro_posts([{"title": "Welcome", "html": str(tmp_path / "missing.html")}])
    assert parse_intro_posts(None) == ()


def test_intro_key_never_collides_with_category():
    assert IntroPost(title="Samsung", html_file=None).key.startswith(INTRO_KEY_PREFIX)


def test_publish_intro_creates_then_skips_unchanged(post):
    api, state = IntroApi(), State()
    cfg = make_config()

    assert asyncio.run(publish_intro(api, cfg, post, state)) is True
    assert state.slots[post.key].message_ids == [100]
    assert api.calls[0][0] == "send" and api.calls[0][3] == {"photo": b"jpeg"}

    assert asyncio.run(publish_intro(api, cfg, post, state)) is False
    assert len(api.calls) == 1


def test_publish_intro_recreates_deleted_post(post):
    api, state = IntroApi(gone={5}), State()
    state.slots[post.key] = sync.CategorySlot(title="Welcome", message_ids=[5], content_hash="stale")

    assert asyncio.run(publish_intro(api, make_config(), post, state)) is True
    assert state.slots[post.key].message_ids == [100]


def test_nav_puts_intro_buttons_above_categories(post):
    captured = {}

    class Api(IntroApi):
        async def send_message(self, chat, text, disable_notification=True, reply_markup=None):
            captured["keyboard"] = reply_markup
            return {"message_id": 200}

    state = State()
    state.slots[post.key] = sync.CategorySlot(title="Welcome", message_ids=[4])
    state.slots["a"] = sync.CategorySlot(title="a", message_ids=[7])
    cfg = make_config(categories=("a",), intro_posts=(post,))

    asyncio.run(publish_nav(Api(), cfg, state))
    rows = captured["keyboard"]["inline_keyboard"]
    assert rows[0][0]["text"] == "Welcome" and rows[0][0]["url"].endswith("/4")
    assert rows[1][0]["text"] == "a"
