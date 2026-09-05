import pytest

from nav import (
    BUTTON_STYLES,
    ButtonStyleError,
    build_keyboard,
    channel_link_id,
    make_button,
    pack_rows,
    message_link,
    render_text,
    validate_style,
)


def test_channel_link_id_strips_prefix():
    assert channel_link_id("-1004494948640") == "4494948640"
    assert channel_link_id(-1002150017620) == "2150017620"
    assert channel_link_id("4494948640") == "4494948640"


def test_message_link_private_channel():
    assert message_link("-1004494948640", None, 7) == "https://t.me/c/4494948640/7"


def test_message_link_public_channel():
    assert message_link("-1002150017620", "iphone_moscow_98", 7) == (
        "https://t.me/iphone_moscow_98/7"
    )
    assert message_link("-1002150017620", "@iphone_moscow_98", 7) == (
        "https://t.me/iphone_moscow_98/7"
    )


def test_build_keyboard_grid():
    entries = [(f"C{i}", f"u{i}") for i in range(5)]
    kb = build_keyboard(entries, columns=3, row_width=99)
    assert [len(row) for row in kb["inline_keyboard"]] == [3, 2]


def test_build_keyboard_appends_extra_rows():
    kb = build_keyboard([("A", "u")], 3, [[{"text": "ЗАКАЗАТЬ", "url": "x"}]])
    assert kb["inline_keyboard"][-1] == [{"text": "ЗАКАЗАТЬ", "url": "x"}]


def test_build_keyboard_truncates_long_labels():
    kb = build_keyboard([("Я" * 100, "u")], 1)
    assert len(kb["inline_keyboard"][0][0]["text"]) == 64


def test_build_keyboard_rejects_zero_columns():
    with pytest.raises(ValueError):
        build_keyboard([("A", "u")], 0)


def test_render_text_escapes():
    assert render_text("<b>x</b>") == "<b>&lt;b&gt;x&lt;/b&gt;</b>"


def test_make_button_omits_default_style():
    assert make_button("A", "u") == {"text": "A", "url": "u"}
    assert make_button("A", "u", "default") == {"text": "A", "url": "u"}


def test_make_button_sets_explicit_style():
    assert make_button("A", "u", "primary")["style"] == "primary"


@pytest.mark.parametrize("style", BUTTON_STYLES)
def test_all_documented_styles_pass_validation(style):
    assert validate_style(style) == style


@pytest.mark.parametrize("style", ["positive", "negative", "secondary", "accent", ""])
def test_styles_rejected_by_bot_api_are_rejected_here(style):
    with pytest.raises(ButtonStyleError):
        validate_style(style)


def test_build_keyboard_applies_style_to_categories_only():
    kb = build_keyboard([("A", "u")], 1, [[make_button("ЗАКАЗАТЬ", "x", "primary")]], "success")
    assert kb["inline_keyboard"][0][0]["style"] == "success"
    assert kb["inline_keyboard"][1][0]["style"] == "primary"


def test_pack_rows_respects_column_cap():
    assert pack_rows(["a", "b", "c", "d"], columns=2, row_width=99) == [[0, 1], [2, 3]]


def test_pack_rows_breaks_on_width():
    labels = ["короткая", "тоже", "очень длинная подпись категории"]
    rows = pack_rows(labels, columns=3, row_width=20)
    assert rows == [[0, 1], [2]]


def test_pack_rows_gives_oversized_label_its_own_row():
    rows = pack_rows(["x" * 50, "a", "b"], columns=3, row_width=20)
    assert rows[0] == [0]


def test_pack_rows_keeps_every_label_once_and_in_order():
    labels = [f"label {i}" for i in range(17)]
    flat = [i for row in pack_rows(labels, 3, 30) for i in row]
    assert flat == list(range(17))


def test_pack_rows_rejects_bad_limits():
    with pytest.raises(ValueError):
        pack_rows(["a"], columns=0, row_width=10)
    with pytest.raises(ValueError):
        pack_rows(["a"], columns=3, row_width=0)
