import pytest

from kasaos.core.exceptions import ValidationError
from kasaos.domain.money import format_amount, parse_amount


@pytest.mark.parametrize("text,expected", [
    ("75", 7500), ("75,5", 7550), ("1.250,50", 125050), ("1250.50", 125050), ("0,01", 1),
    ("1.250", 125000), ("12.5", 1250), ("₺ 1.000.000,00", 100000000), ("3 450,10", 345010),
    ("0,1", 10), ("1.234.567", 123456700),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "0", "-5", "1,234", "1e5", "NaN", "Infinity", "0,00",
                                  "99999999999999"])
def test_parse_amount_rejects(text):
    with pytest.raises(ValidationError):
        parse_amount(text)


def test_kurus_precision_no_float_drift():
    # 0.1 + 0.2 style errors must not occur
    total = sum(parse_amount("0,10") for _ in range(3))
    assert total == 30
    assert format_amount(total) == "0,30 ₺"


@pytest.mark.parametrize("k,text", [(0, "0,00 ₺"), (5, "0,05 ₺"), (125050, "1.250,50 ₺"),
                                    (-99, "-0,99 ₺"), (123456789012, "1.234.567.890,12 ₺")])
def test_format_amount(k, text):
    assert format_amount(k) == text
