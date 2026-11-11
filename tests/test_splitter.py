import pytest

from catalog import Category, CategoryPart
from splitter import SplitConfigError, apply_splits, parse_splits, split_category

SPLITS = parse_splits({
    "Samsung": [
        {"title": "Samsung Galaxy S", "pattern": r"Galaxy S\d"},
        {"title": "Samsung Galaxy A", "pattern": r"Galaxy A\d"},
        {"title": "Samsung Galaxy Tab", "pattern": "Galaxy Tab"},
    ],
})


def make_category(title: str, lines: list[str]) -> Category:
    part = CategoryPart(message_id=1, part_no=1, declared_total=1, lines=tuple(lines))
    return Category(title=title, key=title.casefold(), parts=[part])


def test_split_category_routes_lines_by_series_case_insensitively():
    category = make_category("Samsung", [
        "Galaxy a07 4/128GB - 9000",
        "Galaxy s25 12/256GB - 70000",
        "Galaxy Tab s10 - 50000",
    ])
    result = {c.title: c.lines for c in split_category(category, SPLITS[0])}
    assert result["Samsung Galaxy S"] == ["Galaxy s25 12/256GB - 70000"]
    assert result["Samsung Galaxy A"] == ["Galaxy a07 4/128GB - 9000"]
    assert result["Samsung Galaxy Tab"] == ["Galaxy Tab s10 - 50000"]


def test_split_category_keeps_block_separators_within_series():
    category = make_category("Samsung", [
        "Galaxy s25 128GB - 60000", "", "Galaxy a07 - 9000", "", "Galaxy s26 128GB - 80000",
    ])
    series = {c.title: c.lines for c in split_category(category, SPLITS[0])}
    assert series["Samsung Galaxy S"] == ["Galaxy s25 128GB - 60000", "", "Galaxy s26 128GB - 80000"]
    assert series["Samsung Galaxy A"] == ["Galaxy a07 - 9000"]


def test_split_category_leaves_unmatched_lines_under_source_title():
    category = make_category("Samsung", ["Galaxy Buds 4 - 11000", "Galaxy s25 - 60000"])
    titles = [c.title for c in split_category(category, SPLITS[0])]
    assert titles[-1] == "Samsung"


def test_apply_splits_replaces_only_configured_category():
    categories = {
        "samsung": make_category("Samsung", ["Galaxy s25 - 60000"]),
        "google": make_category("Google", ["Pixel 10 - 50000"]),
    }
    result = apply_splits(categories, SPLITS)
    assert "samsung" not in result
    assert "samsung galaxy s" in result and "google" in result


def test_empty_series_still_exists_for_price_on_request():
    category = make_category("Samsung", ["Galaxy s25 - 60000"])
    series = {c.title: c.lines for c in split_category(category, SPLITS[0])}
    assert series["Samsung Galaxy Tab"] == []


@pytest.mark.parametrize("raw", [
    ["not a dict"],
    {"Samsung": []},
    {"Samsung": [{"title": "S"}]},
    {"Samsung": [{"title": "S", "pattern": "("}]},
])
def test_parse_splits_rejects_bad_config(raw):
    with pytest.raises(SplitConfigError):
        parse_splits(raw)
