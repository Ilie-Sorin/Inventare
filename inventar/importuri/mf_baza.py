"""Citirea exportului contabil MF_BAZA (.xls), comun pentru MF și OI (§9.1)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

import xlrd

from inventar.domain.comun import curata_text, text_optional
from inventar.domain.normalizare import bani, citeste_data, normalizeaza_cont, nr_inventar, nr_inventar_optional

FOAIE = "MF_BAZA"
# Restul celor 61 de coloane (inclusiv reevaluarea) se ignoră intenționat.
COLOANE_OBLIGATORII = ("codinv", "mf_oi", "den", "um", "cont", "pinv")
COLOANE_OPTIONALE = ("seria", "damoc", "dpf", "dnf", "codclas", "nrdoc", "ddoc", "nrdcas", "ddoccas", "explcas",
                     "codinv_v", "mentiuni")
CATEGORIE = {"M": "MF", "O": "OI"}


@dataclass
class RandMF:
    fisier: str
    rand: int  # numărul rândului din Excel (antetul e rândul 1)
    nr_inventar: str
    categorie: str
    denumire: str
    um: str
    serie: str | None
    cont: str
    pret: Decimal
    data_amortizare_integrala: date | None
    data_pif: date | None
    durata_normala: Decimal | None
    cod_clasificare: str | None
    nr_doc_intrare: str | None
    data_doc_intrare: date | None
    nr_doc_casare: str | None
    data_casare: date | None
    explicatie_casare: str | None
    nr_inventar_vechi: str | None
    mentiuni: str | None

    @property
    def casat(self) -> bool:
        return bool(self.nr_doc_casare or self.data_casare)


@dataclass
class RezultatCitire:
    randuri: list
    erori: list[str]


def _valoare(celula: Any, datemode: int) -> Any:
    """Celulele de tip dată devin `date`; restul rămân valori simple."""
    if celula.ctype == xlrd.XL_CELL_DATE:
        return xlrd.xldate.xldate_as_datetime(celula.value, datemode).date()
    if celula.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return None
    return celula.value


def _text_numar(valoare: Any) -> str | None:
    # Documente și coduri pot veni ca număr (13211.0); se păstrează ca text fără zecimale.
    if isinstance(valoare, float) and valoare.is_integer():
        return str(int(valoare))
    return text_optional(str(valoare)) if valoare is not None else None


def randuri_mf_baza(antet: list[str], randuri: Iterable[list[Any]], fisier: str, datemode: int = 0) -> RezultatCitire:
    """Interpretează rândurile foii; separat de xlrd ca să poată fi testat cu date sintetice."""
    index = {curata_text(str(nume)).lower(): i for i, nume in enumerate(antet)}
    lipsa = [c for c in COLOANE_OBLIGATORII if c not in index]
    if lipsa:
        return RezultatCitire([], [f"{fisier}: lipsesc coloanele {', '.join(lipsa)}."])

    rezultat = RezultatCitire([], [])
    for numar, celule in enumerate(randuri, start=2):
        valori = {c: (_valoare(celule[i], datemode) if i < len(celule) else None) for c, i in index.items()}
        if all(v in (None, "") for v in valori.values()):
            continue
        try:
            rezultat.randuri.append(_rand(fisier, numar, valori))
        except ValueError as e:
            rezultat.erori.append(f"{fisier}, rândul {numar}: {e}.")
    return rezultat


def _rand(fisier: str, numar: int, v: dict[str, Any]) -> RandMF:
    mf_oi = curata_text(str(v.get("mf_oi") or "")).upper()
    if mf_oi not in CATEGORIE:
        raise ValueError(f"mf_oi „{mf_oi}” necunoscut (se așteaptă M sau O)")
    denumire = curata_text(str(v.get("den") or ""))
    if not denumire:
        raise ValueError("denumire lipsă")
    if v.get("pinv") in (None, ""):
        raise ValueError("preț de inventar lipsă")
    dnf = v.get("dnf")
    return RandMF(
        fisier=fisier,
        rand=numar,
        nr_inventar=nr_inventar(v.get("codinv")),
        categorie=CATEGORIE[mf_oi],
        denumire=denumire,
        um=curata_text(str(v.get("um") or "")),
        serie=_text_numar(v.get("seria")),
        cont=normalizeaza_cont(v.get("cont")),
        pret=bani(v.get("pinv")),
        data_amortizare_integrala=citeste_data(v.get("damoc")),
        data_pif=citeste_data(v.get("dpf")),
        durata_normala=bani(dnf) if dnf not in (None, "") else None,
        cod_clasificare=_text_numar(v.get("codclas")),
        nr_doc_intrare=_text_numar(v.get("nrdoc")),
        data_doc_intrare=citeste_data(v.get("ddoc")),
        nr_doc_casare=_text_numar(v.get("nrdcas")),
        data_casare=citeste_data(v.get("ddoccas")),
        explicatie_casare=_text_numar(v.get("explcas")),
        nr_inventar_vechi=nr_inventar_optional(v.get("codinv_v")),
        mentiuni=_text_numar(v.get("mentiuni")),
    )


def citeste_mf_baza(continut: bytes, fisier: str) -> RezultatCitire:
    try:
        carte = xlrd.open_workbook(file_contents=continut)
    except Exception:
        return RezultatCitire([], [f"{fisier}: nu este un fișier Excel .xls valid."])
    if FOAIE not in carte.sheet_names():
        return RezultatCitire([], [f"{fisier}: lipsește foaia {FOAIE}."])
    foaie = carte.sheet_by_name(FOAIE)
    if foaie.nrows == 0:
        return RezultatCitire([], [f"{fisier}: foaia {FOAIE} este goală."])
    antet = [str(v) for v in foaie.row_values(0)]
    return randuri_mf_baza(antet, (foaie.row(r) for r in range(1, foaie.nrows)), fisier, carte.datemode)
