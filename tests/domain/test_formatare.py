from datetime import date
from decimal import Decimal

from inventar.formatare import data, data_in_litere, suma


def test_suma():
    assert suma(Decimal("11658.74")) == "11.658,74"
    assert suma(Decimal("11658.74"), separator_mii=False) == "11658,74"
    assert suma(Decimal("1014.85"), separator_mii=False) == "1014,85"
    assert suma(Decimal("-1234567.5")) == "-1.234.567,50"
    assert suma(0) == "0,00"
    assert suma(None) == ""


def test_date():
    assert data(date(2025, 11, 28)) == "28.11.2025"
    assert data_in_litere(date(2025, 11, 28)) == "28 noiembrie 2025"
