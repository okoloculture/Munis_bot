from markup import parse_tiers
from rich_renderer import build_rich_messages, render_rich_message

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
