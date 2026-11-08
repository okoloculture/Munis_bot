import pytest

from markup import parse_tiers
from rich_renderer import (
    EMPTY_TEXT,
    build_rich_messages,
    category_models,
    model_of,
    render_rich_message,
)

TIERS = parse_tiers([{"up_to": 10000, "add": 2000}, {"up_to": None, "add": 4000}])


def test_render_rich_message_builds_two_column_table():
    html = render_rich_message("AirPods", 1, 1, ["AirPods 4 (Type-C) - 8300"], TIERS)
    assert html.startswith("<table bordered><tr><th>AirPods</th><th>Цена</th></tr>")
    assert "<tr><td>AirPods 4 (Type-C)</td><td>10300 ₽</td></tr>" in html
    assert html.endswith("</table>")


def test_render_rich_message_escapes_html_and_marks_parts():
    html = render_rich_message("A & B", 2, 3, ["Watch <S10> - 20000"], TIERS)
    assert "<th>A &amp; B (часть 2/3)</th>" in html
    assert "<td>Watch &lt;S10&gt;</td><td>24000 ₽</td>" in html


def test_render_rich_message_keeps_non_price_lines_full_width():
    html = render_rich_message("Dyson", 1, 1, ["Новинки", "V11 Iron Red - 39100"], TIERS)
    assert '<tr><td colspan="2"><b>Новинки</b></td></tr>' in html


def test_render_rich_message_skips_blank_separators():
    html = render_rich_message("X", 1, 1, ["A - 10000", "", "B - 10000"], TIERS)
    assert html.count("<tr>") == 3


def test_build_rich_messages_fits_large_category_into_one_post():
    lines = [f"Galaxy S26 Ultra 12/512 Titanium Silverblue #{i} - {90000 + i}" for i in range(400)]
    parts = build_rich_messages("Samsung", lines, 1, TIERS)
    assert len(parts) == 1
    assert parts[0].count("<td>") == 800


def test_build_rich_messages_overflows_into_extra_posts():
    lines = [f"Item {i} - {10000 + i}" for i in range(100)]
    parts = build_rich_messages("X", lines, 1, TIERS, capacity=500)
    assert len(parts) > 1
    assert "(часть 1/" in parts[0]



def test_category_models_expands_short_tokens():
    assert category_models("iPhone 17e \\ 17") == (
        "iPhone", [("17e", "iPhone 17e"), ("17", "iPhone 17")],
    )
    assert category_models("Watch SE \\ S10 \\ S11 \\ S12")[1][2] == ("S11", "Watch S11")
    assert category_models("iPhone 17 Pro") == ("", [])


@pytest.mark.parametrize("line, base, keys, expected", [
    ("17e 256GB Black - 61300", "iPhone", ["17e", "17"], "17e"),
    ("17 256GB Black - 72900", "iPhone", ["17e", "17"], "17"),
    ("MHFD4 Neo Citrus A18 Pro (6/5/8/256) - 59600", "MacBook", ["Neo", "Air"], "Neo"),
    ("Watch SE 3 (2025) 40mm - 18500", "Watch", ["SE", "S10", "S11", "S12"], "SE"),
    ("iPad 11 (A16) 2025 128GB - 38100", "iPad", ["Mini", "10", "11"], "11"),
    ("Something else - 10000", "iPhone", ["17e", "17"], None),
])
def test_model_of(line, base, keys, expected):
    assert model_of(line, base, keys) == expected


def test_split_category_gets_a_table_per_model():
    lines = ["17e 256GB Black - 61300", "", "17 256GB Black - 72900", "17 512GB Blue - 88600"]
    html = build_rich_messages("iPhone 17e \\ 17", lines, 1, TIERS, tidy=True)[0]
    assert html.count("<table") == 2
    first, second = html.split("</table>")[:2]
    assert "<th>iPhone 17e</th>" in first and "iPhone 17e 256GB Black" in first
    assert "<th>iPhone 17</th>" in second and second.count("<td>iPhone 17 ") == 2


def test_missing_model_shows_price_on_request():
    lines = ["Watch SE 3 (2025) 40mm - 18500", "Watch S11 (2025) 42mm - 28100"]
    html = build_rich_messages("Watch SE \\ S10 \\ S11", lines, 1, TIERS)[0]
    tables = html.split("</table>")
    assert "<th>Watch S10</th>" in tables[1]
    assert EMPTY_TEXT in tables[1]
    assert "<th>Watch S11</th>" in tables[2]


def test_empty_category_marker_becomes_price_on_request():
    html = build_rich_messages("iPhone 14", ["Товары не найдены"], 1, TIERS)[0]
    assert "Товары не найдены" not in html
    assert EMPTY_TEXT in html


def test_placeholders_appear_once_across_parts():
    lines = [f"S11 item {i} - {10000 + i}" for i in range(60)]
    parts = build_rich_messages("Watch SE \\ S11", lines, 1, TIERS, capacity=400)
    assert len(parts) > 1
    assert sum(part.count(EMPTY_TEXT) for part in parts) == 1
    assert EMPTY_TEXT in parts[-1]
