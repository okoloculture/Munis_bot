from catalog import build_categories, normalize_key, parse_header
from tme_scraper import ChannelMessage, parse_page


def msg(mid, text):
    return ChannelMessage(message_id=mid, text=text)


def test_parse_header_without_parts():
    assert parse_header("📦 iPhone 17 Pro") == ("iPhone 17 Pro", 1, 1)


def test_parse_header_with_parts():
    assert parse_header("📦 Samsung (часть 3/8)") == ("Samsung", 3, 8)


def test_parse_header_ignores_zero_width_prefix():
    assert parse_header("​📦 Google") == ("Google", 1, 1)


def test_parse_header_rejects_plain_line():
    assert parse_header("17 Pro 256GB Blue - 95900") is None


def test_normalize_key_unifies_slashes_and_case():
    assert normalize_key("iPhone 11 \\ 12") == normalize_key("IPHONE 11 / 12")
    assert normalize_key("Watch SE \\ S10 \\ S11") == "watch se / s10 / s11"


def test_build_categories_merges_parts_in_order():
    messages = [
        msg(10, "📦 Samsung (часть 1/2)\n\nA - 1000\nB - 2000"),
        msg(11, "📦 Samsung (часть 2/2)\n\nC - 3000"),
    ]
    categories = build_categories(messages)
    samsung = categories["samsung"]
    assert samsung.message_ids == [10, 11]
    assert samsung.lines == ["A - 1000", "B - 2000", "", "C - 3000"]


def test_build_categories_prefers_newest_repost():
    messages = [
        msg(10, "📦 Google\n\nOld - 1000"),
        msg(1000, "📦 Google\n\nNew - 2000"),
    ]
    categories = build_categories(messages)
    assert categories["google"].message_ids == [1000]
    assert categories["google"].lines == ["New - 2000"]


def test_build_categories_keeps_recent_parts_together():
    messages = [
        msg(500, "📦 Xiaomi (часть 1/2)\n\nA - 1"),
        msg(501, "📦 Xiaomi (часть 2/2)\n\nB - 2"),
    ]
    categories = build_categories(messages)
    assert categories["xiaomi"].message_ids == [500, 501]


def test_build_categories_skips_non_price_messages():
    messages = [
        msg(1, "Уважаемые клиенты, приветствуем вас"),
        msg(2, "ВЫБЕРИТЕ НУЖНУЮ КАТЕГОРИЮ"),
        msg(3, "📦 Honor\n\nX - 1000"),
    ]
    assert list(build_categories(messages)) == ["honor"]


def test_build_categories_skips_header_only_message():
    assert build_categories([msg(3, "📦 Honor")]) == {}


def test_parse_page_reads_ids_and_newlines():
    html = (
        '<div class="tgme_widget_message" data-post="chan/42">'
        '<div class="tgme_widget_message_text">📦 Honor<br/><br/>X - 1000</div></div>'
    )
    messages = parse_page(html)
    assert messages == [ChannelMessage(message_id=42, text="📦 Honor\n\nX - 1000")]
