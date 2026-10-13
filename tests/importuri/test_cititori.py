from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from xlrd import XL_CELL_DATE, XL_CELL_EMPTY, XL_CELL_NUMBER, XL_CELL_TEXT
from xlrd.sheet import Cell

from inventar.importuri.extras import citeste_extras
from inventar.importuri.mf_baza import citeste_mf_baza, randuri_mf_baza

ANTET = ["codinv", "mf_oi", "tip", "den", "um", "seria", "cont", "pinv", "damoc", "ddoc", "nrdcas", "ddoccas",
         "codinv_v", "reev"]


def _t(v):
    return Cell(XL_CELL_TEXT, v)


def _n(v):
    return Cell(XL_CELL_NUMBER, v)


GOL = Cell(XL_CELL_EMPTY, "")


def test_rand_mf_baza_complet():
    rand = [_t("900001"), _t("M"), _t("x"), _t(" SCAUN  ROTATIV "), _t("BUC"), _t("SN-1"), _t("8030000"),
            _n(1234.5), _t("27-Nov-28"), _t("  -   -"), GOL, _t("  -   -"), _n(611388.0), _n(99.0)]
    rezultat = randuri_mf_baza(ANTET, [rand], "mf.xls")
    assert rezultat.erori == []
    [r] = rezultat.randuri
    assert (r.nr_inventar, r.categorie, r.denumire, r.cont) == ("900001", "MF", "SCAUN ROTATIV", "803.00.00")
    assert r.pret == Decimal("1234.50")
    assert r.data_amortizare_integrala == date(2028, 11, 27)
    assert r.data_doc_intrare is None
    assert r.nr_inventar_vechi == "611388"
    assert not r.casat
    assert r.rand == 2


def test_celula_data_xlrd_si_casare():
    # 45000 = 15.03.2023 în sistemul de date Excel 1900.
    rand = [_n(900002.0), _t("O"), GOL, _t("BIROU"), _t("BUC"), GOL, _t("303.02.00.04"), _n(10.0),
            Cell(XL_CELL_DATE, 45000.0), GOL, _t("12"), _t("01-Feb-24"), GOL, GOL]
    [r] = randuri_mf_baza(ANTET, [rand], "oi.xls").randuri
    assert r.nr_inventar == "900002"
    assert r.data_amortizare_integrala == date(2023, 3, 15)
    assert r.casat and r.data_casare == date(2024, 2, 1)


def test_erori_pe_rand_si_randuri_goale_ignorate():
    rau = [_t("900003"), _t("X"), GOL, _t("A"), _t("BUC"), GOL, _t("213"), _n(1.0), GOL, GOL, GOL, GOL, GOL, GOL]
    gol = [GOL] * len(ANTET)
    data_rea = [_t("900004"), _t("M"), GOL, _t("A"), _t("BUC"), GOL, _t("213"), _n(1.0), _t("31-Feb-20"),
                GOL, GOL, GOL, GOL, GOL]
    rezultat = randuri_mf_baza(ANTET, [rau, gol, data_rea], "mf.xls")
    assert rezultat.randuri == []
    assert len(rezultat.erori) == 2
    assert "rândul 2" in rezultat.erori[0] and "mf_oi" in rezultat.erori[0]
    assert "rândul 4" in rezultat.erori[1] and "dată invalidă" in rezultat.erori[1]


def test_coloane_lipsa():
    rezultat = randuri_mf_baza(["codinv", "den"], [], "mf.xls")
    assert "lipsesc coloanele" in rezultat.erori[0]


def test_fisier_care_nu_e_xls():
    assert "nu este un fișier Excel" in citeste_mf_baza(b"nimic", "x.xls").erori[0]


def _extras(randuri) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Tip", "Locatia", "Activitatea", "Persoana", "NrInventar", "NrInventarVechi"])
    for r in randuri:
        ws.append(r)
    continut = BytesIO()
    wb.save(continut)
    return continut.getvalue()


def test_extras():
    continut = _extras([
        ["MijloaceFixe", "Botosani", "Botosani (1Int)", "POP ION", 900001, 0],
        ["ObiecteInventar", " Trezorerie ", "Trezorerie", "BRÎNDUŞA  ANA", "900002", 5184],
        [None, None, None, None, None, None],
        ["Altceva", "x", "y", "z", 1, 0],
    ])
    rezultat = citeste_extras(continut, "extras.xlsx")
    assert [(r.categorie, r.locatie, r.persoana, r.nr_inventar, r.nr_inventar_vechi) for r in rezultat.randuri] == [
        ("MF", "Botosani", "POP ION", "900001", None),
        ("OI", "Trezorerie", "BRÎNDUŞA ANA", "900002", "5184"),
    ]
    assert len(rezultat.erori) == 1 and "rândul 5" in rezultat.erori[0]
