from datetime import date
from decimal import Decimal

import pytest

from inventar.domain.normalizare import (
    bani,
    cheie_nume,
    citeste_data,
    cont_sintetic,
    normalizeaza_cont,
    nr_inventar,
    nr_inventar_optional,
)


@pytest.mark.parametrize("intrare, asteptat", [
    ("8030000", "803.00.00"),
    ("303.02.00.04", "303.02.00.04"),
    ("212.09.01", "212.09.01"),
    ("213", "213"),
    (" 303 02 00 01 ", "303.02.00.01"),
    (8030000.0, "803.00.00"),
    (213, "213"),
])
def test_cont(intrare, asteptat):
    assert normalizeaza_cont(intrare) == asteptat


@pytest.mark.parametrize("intrare", ["", "  ", "abc", "21"])
def test_cont_invalid(intrare):
    with pytest.raises(ValueError):
        normalizeaza_cont(intrare)


def test_cont_sintetic():
    assert cont_sintetic("303.02.00.04") == "303"
    assert cont_sintetic("803.00.00") == "803"


@pytest.mark.parametrize("intrare, asteptat", [
    ("27-Nov-20", date(2020, 11, 27)),
    ("01-May-97", date(1997, 5, 1)),
    ("31-Dec-68", date(2068, 12, 31)),
    ("01-Jan-69", date(1969, 1, 1)),
    ("01-Jan-00", date(2000, 1, 1)),
    ("15-feb-1999", date(1999, 2, 15)),
    ("  -   -", None),
    ("", None),
    (None, None),
    (date(2021, 4, 20), date(2021, 4, 20)),
])
def test_data(intrare, asteptat):
    assert citeste_data(intrare) == asteptat


@pytest.mark.parametrize("intrare", ["32-Jan-20", "01-Xyz-20", "2020-01-01x", "ieri"])
def test_data_invalida(intrare):
    with pytest.raises(ValueError):
        citeste_data(intrare)


@pytest.mark.parametrize("intrare, asteptat", [
    (116647.0, "116647"), (116647, "116647"), (" 115675 ", "115675"), ("A-12", "A-12"),
])
def test_nr_inventar(intrare, asteptat):
    assert nr_inventar(intrare) == asteptat


@pytest.mark.parametrize("intrare", ["", None, 0, 0.0, "  "])
def test_nr_inventar_obligatoriu(intrare):
    with pytest.raises(ValueError):
        nr_inventar(intrare)


@pytest.mark.parametrize("intrare, asteptat", [
    (0, None), (0.0, None), ("", None), ("0", None), (None, None), (611388.0, "611388"), ("5184", "5184"),
])
def test_nr_inventar_vechi(intrare, asteptat):
    assert nr_inventar_optional(intrare) == asteptat


@pytest.mark.parametrize("intrare, asteptat", [
    (31287.86, Decimal("31287.86")),
    (0.1 + 0.2, Decimal("0.30")),
    (3720.0, Decimal("3720.00")),
    ("49,99", Decimal("49.99")),
    (697942, Decimal("697942.00")),
])
def test_bani(intrare, asteptat):
    rezultat = bani(intrare)
    assert rezultat == asteptat
    assert rezultat.as_tuple().exponent == -2


def test_cheie_nume_ignora_majuscule_diacritice_si_sedila():
    assert cheie_nume("Brânduşa  ţuţu") == cheie_nume("BRANDUSA TUTU") == cheie_nume("BRÂNDUȘA ȚUȚU")
