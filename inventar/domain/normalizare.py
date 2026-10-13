"""Normalizarea valorilor din exportul contabil și din extras (§9.1).

Funcțiile primesc valori brute (text sau număr, cum le dă xlrd/openpyxl) și
ridică ValueError cu mesaj în română când valoarea nu poate fi interpretată.
"""
import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_LUNI = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATA = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})$")


def _text(valoare: object) -> str:
    """Numerele întregi venite din Excel ca float (116647.0) devin text fără zecimale."""
    if valoare is None:
        return ""
    if isinstance(valoare, float) and valoare.is_integer():
        return str(int(valoare))
    return str(valoare).strip()


def normalizeaza_cont(valoare: object) -> str:
    """Păstrează doar cifrele și le grupează 3 + 2 + 2 + …: 8030000 → 803.00.00."""
    cifre = re.sub(r"\D", "", _text(valoare))
    if len(cifre) < 3:
        raise ValueError(f"cont invalid: „{_text(valoare)}”")
    grupuri = [cifre[:3]] + [cifre[i:i + 2] for i in range(3, len(cifre), 2)]
    return ".".join(grupuri)


def cont_sintetic(cont: str) -> str:
    return cont[:3]


def citeste_data(valoare: object) -> date | None:
    """Text `dd-Mon-yy` (sau `dd-Mon-yyyy`); `  -   -` sau gol → None.

    Celulele de tip dată sunt convertite de cititor în `date` înainte de a ajunge aici.
    """
    if isinstance(valoare, datetime):
        return valoare.date()
    if isinstance(valoare, date):
        return valoare
    text = _text(valoare)
    if not text.replace("-", "").strip():
        return None
    potrivire = _DATA.match(text)
    if not potrivire:
        raise ValueError(f"dată invalidă: „{text}”")
    zi, luna_text, an_text = potrivire.groups()
    luna = _LUNI.get(luna_text.lower())
    if luna is None:
        raise ValueError(f"lună necunoscută în data „{text}”")
    an = int(an_text)
    if len(an_text) == 2:
        # Pivotul 69: așa interpretează și exportul contabil anii pe 2 cifre.
        an += 1900 if an >= 69 else 2000
    try:
        return date(an, luna, int(zi))
    except ValueError:
        raise ValueError(f"dată invalidă: „{text}”") from None


def nr_inventar(valoare: object) -> str:
    text = _text(valoare)
    if not text or text == "0":
        raise ValueError("număr de inventar lipsă")
    return text


def nr_inventar_optional(valoare: object) -> str | None:
    """Pentru numărul vechi: gol sau 0 înseamnă lipsă."""
    text = _text(valoare)
    return None if not text or text == "0" else text


def bani(valoare: object) -> Decimal:
    """Float-urile din xlrd se rotunjesc la 2 zecimale înainte de conversie, ca să nu
    apară artefacte binare (0.30000000000000004)."""
    try:
        if isinstance(valoare, float):
            rezultat = Decimal(str(round(valoare, 2)))
        else:
            rezultat = Decimal(_text(valoare).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"valoare invalidă: „{_text(valoare)}”") from None
    return rezultat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cheie_nume(nume: str) -> str:
    """Forma de comparație a unui nume: fără diacritice, majuscule și spații multiple."""
    descompus = unicodedata.normalize("NFKD", nume.casefold())
    fara_diacritice = "".join(c for c in descompus if not unicodedata.combining(c))
    return " ".join(fara_diacritice.split())
