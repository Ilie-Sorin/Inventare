"""Formatarea numerelor și datelor pentru afișare (ecrane, PDF, e-mail)."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

LUNI = ("ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie",
        "octombrie", "noiembrie", "decembrie")


def suma(valoare: Decimal | int | None, separator_mii: bool = True) -> str:
    """Virgulă zecimală; pe liste fără separator de mii (4034,10), în ecrane cu punct (4.034,10)."""
    if valoare is None:
        return ""
    text = f"{Decimal(valoare).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", "." if separator_mii else "")


def data(valoare: date | None) -> str:
    return f"{valoare:%d.%m.%Y}" if valoare else ""


def data_in_litere(valoare: date) -> str:
    return f"{valoare.day} {LUNI[valoare.month - 1]} {valoare.year}"
