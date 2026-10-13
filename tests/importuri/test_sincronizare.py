"""Sincronizarea anuală cu exportul contabil (§9.4): fiecare tip de diferență are test."""
import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from inventar.domain.comun import EroareValidare
from inventar.domain.documente import LinieNoua, salveaza_ciorna, valideaza
from inventar.domain.generare import Perimetru, blocheaza, data_ultimei_sincronizari, genereaza
from inventar.domain.stoc import detinatori_la
from inventar.importuri.mf_baza import RezultatCitire
from inventar.importuri.sincronizare import abandoneaza, analizeaza, aplica, incarca
from inventar.models import Bun, Document, InventarLinie, Jurnal
from tests.conftest import CONSULTARE, OPERATOR
from tests.importuri.test_import_initial import bun as rand_export

START = date(2025, 1, 1)


@pytest.fixture
def lume(session, persoana, bunuri, initial):
    a = persoana("ANA")
    b1, b2, b3 = bunuri("1", "2", "3", cont="213.01", pret="100.00")
    [b4] = bunuri("4", categorie="OI", cont="303.02", pret="10.00")
    initial(START, [(b1, a), (b2, a), (b3, a), (b4, a)])
    return {"a": a, "b1": b1, "b2": b2, "b3": b3, "b4": b4}


def export_identic(**modificari) -> list:
    """Exportul care corespunde exact aplicației; `modificari` = {nr: {camp: valoare}} sau {nr: None} (lipsă)."""
    randuri = {
        "1": rand_export("1", pret="100.00", cont="213.01"),
        "2": rand_export("2", pret="100.00", cont="213.01"),
        "3": rand_export("3", pret="100.00", cont="213.01"),
        "4": rand_export("4", "OI", "303.02", "10.00"),
    }
    for nr, valori in modificari.items():
        if valori is None:
            randuri.pop(nr, None)
        elif nr in randuri:
            randuri[nr] = replace(randuri[nr], **valori)
        else:
            randuri[nr] = rand_export(nr, **valori)
    return [RezultatCitire(list(randuri.values()), [])]


def _tipuri(analiza) -> dict[str, list[str]]:
    rezultat: dict[str, list[str]] = {}
    for d in analiza.diferente:
        rezultat.setdefault(d.tip, []).append(d.nr_inventar)
    return rezultat


def _aplica_tot(session, exporturi):
    s = incarca(session, OPERATOR, exporturi, [{"original": "MF.xls", "salvat": "mf_0.xls"}], "dir")
    aplica(session, OPERATOR, s.id, exporturi, {d.id for d in s.diferente})
    return s


def test_export_identic_fara_diferente(session, lume):
    analiza = analizeaza(session, export_identic())
    assert analiza.erori == [] and analiza.diferente == []
    assert {(t.categorie, t.cont): (t.export_numar, t.app_numar) for t in analiza.totaluri} == {
        ("MF", "213.01"): (3, 3), ("OI", "303.02"): (1, 1)}


def test_bun_nou_intra_la_nerepartizate(session, lume):
    export = export_identic(**{"9": {"categorie": "MF", "cont": "214.05", "pret": Decimal("55.00"),
                                     "data_doc_intrare": date(2025, 5, 3), "nr_doc_intrare": "77"}})
    assert _tipuri(analizeaza(session, export)) == {"BUN_NOU": ["9"]}
    _aplica_tot(session, export)
    nou = session.scalar(select(Bun).where(Bun.nr_inventar == "9"))
    assert (nou.pret, nou.cont.simbol, nou.cont.sintetic, nou.data_doc_intrare) == (
        Decimal("55.00"), "214.05", "214", date(2025, 5, 3))
    assert nou.id not in detinatori_la(session, date(2026, 1, 1), [nou.id])  # nerepartizat


def test_casare_propune_iesire(session, lume):
    export = export_identic(**{"2": {"nr_doc_casare": "PV 12", "data_casare": date(2025, 9, 30),
                                     "explicatie_casare": "uzură"}})
    analiza = analizeaza(session, export)
    # Câmpurile de casare se actualizează separat (MODIFICAT); ieșirea e propunerea CASARE.
    assert _tipuri(analiza) == {"CASARE": ["2"], "MODIFICAT": ["2"]}
    casare = next(d for d in analiza.diferente if d.tip == "CASARE")
    assert casare.aplicabila and casare.detalii["detinator"] == "ANA"
    _aplica_tot(session, export)
    iesire = session.scalar(select(Document).where(Document.tip == "IESIRE"))
    assert (iesire.numar, iesire.data, iesire.motiv_iesire, iesire.stare) == ("PV 12", date(2025, 9, 30), "CASARE",
                                                                              "VALIDAT")
    assert detinatori_la(session, date(2025, 9, 30), [lume["b2"].id]) == {lume["b2"].id: None}
    # La sincronizarea următoare bunul nu mai e propus (a ieșit deja).
    assert "CASARE" not in _tipuri(analizeaza(session, export))


def test_casare_fara_data_doar_semnalata(session, lume):
    analiza = analizeaza(session, export_identic(**{"2": {"nr_doc_casare": "PV 12"}}))
    casare = next(d for d in analiza.diferente if d.tip == "CASARE")
    assert not casare.aplicabila


def test_casare_bun_nerepartizat_nu_cere_iesire(session, lume, bunuri):
    bunuri("5", cont="213.01", pret="1.00")
    export = export_identic(**{"5": {"cont": "213.01", "pret": Decimal("1.00"), "nr_doc_casare": "1",
                                     "data_casare": date(2025, 3, 1)}})
    assert _tipuri(analizeaza(session, export)) == {"MODIFICAT": ["5"]}


def test_bun_disparut_si_apoi_absent(session, lume):
    export = export_identic(**{"3": None})
    assert _tipuri(analizeaza(session, export)) == {"DISPARUT": ["3"]}
    _aplica_tot(session, export)
    assert lume["b3"].prezent_in_export is False
    # Încă la o persoană și tot absent din contabilitate: rămâne semnalat.
    assert _tipuri(analizeaza(session, export)) == {"ABSENT": ["3"]}
    # Revine în export: e din nou prezent.
    _aplica_tot(session, export_identic())
    assert lume["b3"].prezent_in_export is True


def test_bun_iesit_si_disparut_nu_e_semnalat(session, lume):
    doc = salveaza_ciorna(session, OPERATOR, "IESIRE", date(2025, 6, 1), "1",
                          [LinieNoua(lume["b3"].id, lume["a"].id, None)], motiv_iesire="VANZARE")
    valideaza(session, OPERATOR, doc.id)
    assert analizeaza(session, export_identic(**{"3": None})).diferente == []


def test_modificari_fara_istoric(session, lume):
    export = export_identic(**{"1": {"pret": Decimal("150.00"), "cont": "214.01", "denumire": "BUN REDENUMIT",
                                     "serie": "S1", "data_amortizare_integrala": date(2030, 1, 1),
                                     "nr_inventar_vechi": "777"},
                               "4": {"categorie": "MF", "cont": "213.01"}})
    analiza = analizeaza(session, export)
    assert _tipuri(analiza) == {"MODIFICAT": ["1", "4"]}
    campuri = next(d for d in analiza.diferente if d.nr_inventar == "1").detalii["campuri"]
    assert set(campuri) == {"pret", "cont", "denumire", "serie", "data_amortizare_integrala", "nr_inventar_vechi"}
    assert campuri["pret"] == ["100.00", "150.00"]
    _aplica_tot(session, export)
    b1 = lume["b1"]
    assert (b1.pret, b1.cont.simbol, b1.denumire, b1.serie, b1.nr_inventar_vechi) == (
        Decimal("150.00"), "214.01", "BUN REDENUMIT", "S1", "777")
    assert (lume["b4"].categorie, lume["b4"].cont.simbol) == ("MF", "213.01")


def test_aplicarea_marcheaza_inventarele_generate_nu_si_blocate(session, lume):
    generat = genereaza(session, OPERATOR, date(2025, 11, 28), Perimetru())
    blocat = genereaza(session, OPERATOR, date(2025, 11, 28), Perimetru(categorii=("MF",)))
    blocheaza(session, OPERATOR, blocat.id)
    _aplica_tot(session, export_identic(**{"1": {"pret": Decimal("150.00")}}))
    assert (generat.stare, blocat.stare) == ("NEACTUALIZAT", "BLOCAT")
    pret = session.scalar(select(InventarLinie.pret).where(InventarLinie.inventar_id == blocat.id,
                                                           InventarLinie.nr_inventar == "1"))
    assert pret == Decimal("100.00")


def test_doar_ce_e_selectat(session, lume):
    export = export_identic(**{"1": {"pret": Decimal("150.00")}, "9": {"cont": "213.01"}})
    s = incarca(session, OPERATOR, export, [], "dir")
    nou = next(d for d in s.diferente if d.tip == "BUN_NOU")
    aplica(session, OPERATOR, s.id, export, {nou.id})
    assert lume["b1"].pret == Decimal("100.00")
    assert {d.tip: d.actiune for d in s.diferente} == {"BUN_NOU": "APLICAT", "MODIFICAT": "IGNORAT"}
    assert s.stare == "APLICATA"
    with pytest.raises(EroareValidare, match="deja"):
        aplica(session, OPERATOR, s.id, export, set())


def test_aplicarea_e_atomica(session, lume, persoana):
    """O ieșire care nu se poate valida oprește toată aplicarea."""
    alt = persoana("ALT")
    doc = salveaza_ciorna(session, OPERATOR, "TRANSFER", date(2025, 10, 1), "1",
                          [LinieNoua(lume["b2"].id, lume["a"].id, alt.id)])
    valideaza(session, OPERATOR, doc.id)
    export = export_identic(**{"2": {"nr_doc_casare": "PV", "data_casare": date(2025, 9, 30)},
                               "1": {"pret": Decimal("999.00")}})
    s = incarca(session, OPERATOR, export, [], "dir")
    with pytest.raises(EroareValidare, match="ulterioară"):
        aplica(session, OPERATOR, s.id, export, {d.id for d in s.diferente})
    session.rollback()
    assert lume["b1"].pret == Decimal("100.00") and s.stare == "INCARCATA"


def test_situatia_schimbata_intre_incarcare_si_aplicare(session, lume):
    export = export_identic(**{"1": {"pret": Decimal("150.00")}})
    s = incarca(session, OPERATOR, export, [], "dir")
    alt_export = export_identic(**{"1": {"pret": Decimal("175.00")}})
    with pytest.raises(EroareValidare, match="schimbat"):
        aplica(session, OPERATOR, s.id, alt_export, {d.id for d in s.diferente})


def test_erori_blocante(session, lume):
    duplicat = export_identic()
    duplicat[0].randuri.append(rand_export("1"))
    assert any("de mai multe ori" in e for e in analizeaza(session, duplicat).erori)
    with pytest.raises(EroareValidare):
        incarca(session, OPERATOR, duplicat, [], "dir")


def test_fara_import_initial(session):
    assert any("importul inițial" in e for e in analizeaza(session, export_identic()).erori)


def test_drepturi_si_abandonare(session, lume):
    from inventar.drepturi import AccesInterzis

    with pytest.raises(AccesInterzis):
        incarca(session, CONSULTARE, export_identic(), [], "dir")
    s = incarca(session, OPERATOR, export_identic(**{"1": {"pret": Decimal("1.00")}}), [], "dir")
    abandoneaza(session, OPERATOR, s.id)
    assert s.stare == "ABANDONATA" and lume["b1"].pret == Decimal("100.00")


def test_jurnal_si_data_ultimei_sincronizari(session, lume):
    session.scalar(select(Document).where(Document.tip == "INITIAL")).creat_la = datetime(2025, 1, 1)
    session.commit()
    s = _aplica_tot(session, export_identic(**{"1": {"pret": Decimal("150.00")}}))
    assert data_ultimei_sincronizari(session) == s.incarcat_la.date()
    actiuni = list(session.scalars(select(Jurnal.actiune).where(Jurnal.actiune.like("SINCRONIZARE_%"))
                                   .order_by(Jurnal.id)))
    assert actiuni == ["SINCRONIZARE_INCARCATA", "SINCRONIZARE_APLICATA"]
    detalii = json.loads(session.scalars(select(Jurnal.detalii_json).where(
        Jurnal.actiune == "SINCRONIZARE_APLICATA")).one())
    assert detalii["aplicate"] == {"MODIFICAT": 1}
