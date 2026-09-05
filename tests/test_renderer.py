import pytest

from markup import parse_tiers
from renderer import (
    DEFAULT_PRICE_FORMAT,
    PriceFormatError,
    build_messages,
    count_price_lines,
    distribute,
    render_message,
    rewrite_line,
    rewrite_prices,
    split_blocks,
    validate_price_format,
)

TIERS = parse_tiers([
    {"up_to": 10000, "add": 2000},
    {"up_to": 80000, "add": 5000},
    {"up_to": 110000, "add": 6000},
    {"up_to": None, "add": 13000},
])

# Формат «как в опте» — им проверяем, что меняется только число цены.
RAW_FORMAT = "{name} - {price}"


@pytest.mark.parametrize(
    "line,expected",
    [
        ("16 Pro 128GB Desert 🇨🇳 (Dual-Sim) - 92600", "16 Pro 128GB Desert 🇨🇳 (Dual-Sim) - 98600"),
        ("17 Max 256GB Blue eSim 🇯🇵 109000", "17 Max 256GB Blue eSim 🇯🇵 - 115000"),
        ("AirPods 4 (Type-C) - 9600", "AirPods 4 (Type-C) - 11600"),
        ("Galaxy Ring Titanium Gold 10 Q500 🇬🇧 - 18300", "Galaxy Ring Titanium Gold 10 Q500 🇬🇧 - 23300"),
    ],
)
def test_rewrite_line_replaces_only_the_price(line, expected):
    assert rewrite_line(line, TIERS, price_format=RAW_FORMAT) == expected


@pytest.mark.parametrize(
    "line",
    [
        "",
        "📦 iPhone 17 Pro",
        "Watch S11 (2025) 42mm Jet Black (S/M)",
        "Galaxy S24 Ultra 512GB",
        "Скидка 500",
    ],
)
def test_rewrite_line_leaves_non_price_lines(line):
    assert rewrite_line(line, TIERS) == line


def test_rewrite_prices_preserves_line_count():
    lines = ["A - 9600", "", "B - 12000", "заголовок"]
    assert len(rewrite_prices(lines, TIERS, price_format=RAW_FORMAT)) == len(lines)


def test_count_price_lines():
    assert count_price_lines(["A - 9600", "", "просто текст", "B - 12000"]) == 2


def test_split_blocks_groups_on_blank_lines():
    lines = ["a", "b", "", "", "c", "", "d"]
    assert split_blocks(lines) == [["a", "b"], ["c"], ["d"]]


def test_distribute_fills_every_slot():
    blocks = [[f"line {i}"] for i in range(10)]
    parts = distribute(blocks, slots=3, capacity=4000)
    assert len(parts) == 3
    assert all(part for part in parts)
    assert sum(line.startswith("line") for part in parts for line in part) == 10


def test_distribute_preserves_order():
    blocks = [[f"line {i}"] for i in range(9)]
    parts = distribute(blocks, slots=3, capacity=4000)
    flat = [line for part in parts for line in part if line]
    assert flat == [f"line {i}" for i in range(9)]


def test_distribute_adds_parts_when_capacity_exceeded():
    blocks = [["x" * 200] for _ in range(10)]
    parts = distribute(blocks, slots=1, capacity=500)
    assert len(parts) > 1
    assert all(sum(len(line) + 1 for line in part) <= 500 for part in parts)


def test_distribute_splits_oversized_block():
    parts = distribute([["y" * 100 for _ in range(10)]], slots=1, capacity=400)
    assert len(parts) > 1


def test_render_message_marks_parts():
    assert render_message("Samsung", 2, 3, ["a"]).startswith("📦 <b>Samsung (часть 2/3)</b>")
    assert render_message("Samsung", 1, 1, ["a"]).startswith("📦 <b>Samsung</b>")


def test_render_message_escapes_html():
    assert "&lt;b&gt;" in render_message("X", 1, 1, ["<b>hack</b>"])


def test_build_messages_respects_telegram_limit():
    lines = []
    for i in range(400):
        lines.append(f"Item {i} 🇯🇵 (E-Sim) - {50000 + i}")
        if i % 5 == 4:
            lines.append("")
    messages = build_messages("Samsung", lines, slots=9, tiers=TIERS)
    assert len(messages) >= 9
    assert all(len(message) <= 4096 for message in messages)


def test_build_messages_keeps_every_position():
    lines = [f"Item {i} - {10000 + i * 7}" for i in range(50)]
    messages = build_messages("Xiaomi", lines, slots=3, tiers=TIERS, price_format=RAW_FORMAT)
    rendered = "\n".join(messages)
    for i in range(50):
        assert f"Item {i} -" in rendered


def test_build_messages_applies_markup():
    messages = build_messages("Test", ["A - 9600"], slots=1, tiers=TIERS)
    assert "A — 11600 ₽" in messages[0]



@pytest.mark.parametrize(
    "line,expected",
    [
        ("Pixel 7a 128GB Coral 🇦🇺 - 26000", "Pixel 7a 128GB Coral 🇦🇺 — 31000 ₽"),
        ("AirPods 4 (Type-C) - 9600", "AirPods 4 (Type-C) — 11600 ₽"),
        ("17 Max 256GB Blue eSim 🇯🇵 109000", "17 Max 256GB Blue eSim 🇯🇵 — 115000 ₽"),
        ("Watch S11 42mm Jet Black (S/M) (Мятая 📦) - 28100", "Watch S11 42mm Jet Black (S/M) (Мятая 📦) — 33100 ₽"),
    ],
)
def test_default_format_normalises_separator(line, expected):
    assert rewrite_line(line, TIERS, price_format=DEFAULT_PRICE_FORMAT) == expected


def test_raw_format_keeps_source_style():
    assert rewrite_line("Pixel 7a 128GB Coral 🇦🇺 - 26000", TIERS, price_format=RAW_FORMAT) == (
        "Pixel 7a 128GB Coral 🇦🇺 - 31000"
    )


def test_format_does_not_eat_hyphen_inside_name():
    assert rewrite_line("Wi-Fi адаптер Type-C 9600", TIERS) == "Wi-Fi адаптер Type-C — 11600 ₽"


def test_build_messages_honours_price_format():
    messages = build_messages("Test", ["A - 9600"], slots=1, tiers=TIERS, price_format=RAW_FORMAT)
    assert "A - 11600" in messages[0]


@pytest.mark.parametrize("template", ["{name}", "{price}", "{name} {cost}", "{name} {price:!}"])
def test_validate_price_format_rejects_broken_templates(template):
    with pytest.raises(PriceFormatError):
        validate_price_format(template)


def test_validate_price_format_accepts_default():
    assert validate_price_format(DEFAULT_PRICE_FORMAT) == DEFAULT_PRICE_FORMAT
