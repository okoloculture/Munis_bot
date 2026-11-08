import pytest

from names import product_type, tidy_name


@pytest.mark.parametrize("title, name, expected", [
    ("MacBook Neo \\ Air", "MHFD4 Neo Citrus A18 Pro (6/5/8/256)",
     "MacBook Neo Citrus A18 Pro 8/256 (MHFD4)"),
    ("MacBook Neo \\ Air", "MDHF4 Air 13 Midnight M5 (10/10/16/1TB)",
     "MacBook Air 13 Midnight M5 16/1TB (MDHF4)"),
    ("MacBook Pro", "MGDR4 Pro 14 Space Black M5 Pro (15/16/24/1TB)",
     "MacBook Pro 14 Space Black M5 Pro 24/1TB (MGDR4)"),
    ("iPhone 17e \\ 17", "17e 256GB Black 🇭🇰 (Sim + E-Sim)",
     "iPhone 17e 256GB Black 🇭🇰 (Sim + E-Sim)"),
    ("iPhone 18 Pro Max", "18 Pro Max 1TB Silver 🇯🇵 (E-Sim)",
     "iPhone 18 Pro Max 1TB Silver 🇯🇵 (E-Sim)"),
    ("Watch SE \\ S10 \\ S11 \\ S12", "Watch S11 (2025) 42mm Jet Black (S/M)",
     "Apple Watch S11 (2025) 42mm Jet Black (S/M)"),
    ("Ultra Watch", "Watch Ultra 3 (2025) Black case Milanese Loop (S)",
     "Apple Watch Ultra 3 (2025) Black case Milanese Loop (S)"),
    ("iPad Air", "iPad Air 11 (M4) 2026 128GB Wi‑Fi Blue 🇺🇸",
     "iPad Air 11 (M4) 2026 128GB Wi‑Fi Blue 🇺🇸"),
])
def test_tidy_name(title, name, expected):
    assert tidy_name(title, name) == expected


def test_tidy_name_keeps_brand_categories_verbatim():
    assert tidy_name("Samsung", "Galaxy Buds 4 Black 🇰🇿") == "Galaxy Buds 4 Black 🇰🇿"
    assert tidy_name("AirPods", "AirPods 4 (Type-C)") == "AirPods 4 (Type-C)"


def test_tidy_name_leaves_unusual_mac_lines_alone():
    assert tidy_name("MacBook Pro", "Pro 14 M5 (24/1TB)") == "MacBook Pro 14 M5 (24/1TB)"


def test_product_type():
    assert product_type("iPad Mini \\ 10 \\ 11") == "iPad"
    assert product_type("Xiaomi") is None
