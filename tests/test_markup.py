import pytest

from markup import MarkupConfigError, MarkupTier, apply_markup, markup_for, parse_tiers

RAW_TIERS = [
    {"up_to": 10000, "add": 2000},
    {"up_to": 15000, "add": 3000},
    {"up_to": 40000, "add": 4000},
    {"up_to": 80000, "add": 5000},
    {"up_to": 110000, "add": 6000},
    {"up_to": 135000, "add": 7000},
    {"up_to": 160000, "add": 8000},
    {"up_to": 185000, "add": 9000},
    {"up_to": None, "add": 13000},
]


@pytest.fixture
def tiers():
    return parse_tiers(RAW_TIERS)


@pytest.mark.parametrize(
    "price,expected",
    [
        (9400, 11400),
        (10000, 12000),
        (10001, 13001),
        (13300, 16300),
        (15000, 18000),
        (15001, 19001),
        (33100, 37100),
        (40000, 44000),
        (80000, 85000),
        (103000, 109000),
        (110000, 116000),
        (135000, 142000),
        (160000, 168000),
        (185000, 194000),
        (185001, 198001),
        (300000, 313000),
    ],
)
def test_tier_boundaries(tiers, price, expected):
    assert apply_markup(price, tiers) == expected


def test_markup_for_returns_step(tiers):
    assert markup_for(9999, tiers) == 2000
    assert markup_for(1_000_000, tiers) == 13000


def test_round_to_nearest_rounds_up(tiers):
    assert apply_markup(9401, tiers, round_to=100) == 11500
    assert apply_markup(9400, tiers, round_to=1000) == 12000


def test_round_to_zero_keeps_exact(tiers):
    assert apply_markup(9401, tiers, round_to=0) == 11401


def test_last_tier_must_be_open_ended():
    with pytest.raises(MarkupConfigError):
        parse_tiers([{"up_to": 1000, "add": 100}])


def test_bounds_must_ascend():
    with pytest.raises(MarkupConfigError):
        parse_tiers([
            {"up_to": 20000, "add": 100},
            {"up_to": 10000, "add": 200},
            {"up_to": None, "add": 300},
        ])


def test_open_bound_only_at_the_end():
    with pytest.raises(MarkupConfigError):
        parse_tiers([{"up_to": None, "add": 100}, {"up_to": None, "add": 200}])


def test_negative_add_rejected():
    with pytest.raises(MarkupConfigError):
        parse_tiers([{"up_to": None, "add": -1}])


def test_parsed_tiers_are_frozen(tiers):
    assert isinstance(tiers[0], MarkupTier)
    with pytest.raises(Exception):
        tiers[0].add = 1


PCT_TIERS = [
    {"up_to": 40000, "pct": 10},
    {"up_to": 70000, "pct": 7},
    {"up_to": 100000, "pct": 6},
    {"up_to": None, "pct": 5},
]


@pytest.mark.parametrize(
    "price,expected",
    [(9600, 10560), (40000, 44000), (40001, 42801), (70000, 74900),
     (100000, 106000), (150000, 157500)],
)
def test_percentage_tiers(price, expected):
    assert apply_markup(price, parse_tiers(PCT_TIERS)) == expected


def test_percentage_markup_reported_in_rubles():
    assert markup_for(50000, parse_tiers(PCT_TIERS)) == 3500


def test_percentage_and_absolute_tiers_can_be_mixed():
    tiers = parse_tiers([{"up_to": 10000, "add": 2000}, {"up_to": None, "pct": 5}])
    assert apply_markup(9000, tiers) == 11000
    assert apply_markup(100000, tiers) == 105000


def test_tier_needs_exactly_one_of_add_or_pct():
    with pytest.raises(MarkupConfigError):
        parse_tiers([{"up_to": None}])
    with pytest.raises(MarkupConfigError):
        parse_tiers([{"up_to": None, "add": 100, "pct": 5}])


def test_negative_pct_rejected():
    with pytest.raises(MarkupConfigError):
        parse_tiers([{"up_to": None, "pct": -1}])
