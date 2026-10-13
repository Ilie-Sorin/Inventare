import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from inventar.domain.comun import EroareValidare
from inventar.domain.incadrare import incadrare_la
from inventar.drepturi import AccesInterzis
from inventar.importuri.extras import RandExtras
from inventar.importuri.import_initial import (
    AV_CASATE,
    AV_FARA_PERSOANA,
    AV_NR_VECHI,
    analizeaza,
    confirma,
    perechi_similare,
)
from inventar.importuri.mf_baza import RandMF, RezultatCitire
from inventar.models import Bun, Document, Jurnal, LinieDocument, Persoana
from tests.conftest import CONSULTARE, OPERATOR

START = date(2025, 11, 28)


def bun(nr: str, categorie: str = "MF", cont: str = "213.01", pret: str = "100.00", **extra) -> RandMF:
    valori = dict(
        fisier="mf.xls", rand=2, nr_inventar=nr, categorie=categorie, denumire=f"BUN {nr}", um="BUC", serie=None,
        cont=cont, pret=Decimal(pret), data_amortizare_integrala=None, data_pif=None, durata_normala=None,
        cod_clasificare=None, nr_doc_intrare=None, data_doc_intrare=None, nr_doc_casare=None, data_casare=None,
        explicatie_casare=None, nr_inventar_vechi=None, mentiuni=None,
    )
    valori.update(extra)
    return RandMF(**valori)


def rand(nr: str, persoana: str, categorie: str = "MF", locatie: str = "Botosani",
         activitate: str = "Botosani (1Int)", vechi: str | None = None, nr_rand: int = 2) -> RandExtras:
    return RandExtras(nr_rand, categorie, locatie, activitate, persoana, nr, vechi)


def citire(randuri) -> RezultatCitire:
    return RezultatCitire(list(randuri), [])


def _analiza(session, export, extras, decizii=None, data=START):
    return analizeaza(session, [citire(export)], citire(extras), data, decizii)


EXPORT = [bun("1", pret="4034.10"), bun("2", pret="7624.64"), bun("3", "OI", "303.02.00.04", "15.50")]
EXTRAS = [rand("1", "HRITCU MARCELA"), rand("2", "HRITCU MARCELA"),
          rand("3", "CONSTANTIN ANA", "OI", "Trezorerie", "Trezorerie")]


def test_import_reusit(session):
    raport = _analiza(session, EXPORT, EXTRAS)
    assert raport.poate_confirma
    assert raport.statistici["categorii"]["MF"]["valoare_repartizata"] == Decimal("11658.74")
    # Raportul nu salvează nimic.
    assert session.scalar(select(func.count()).select_from(Bun)) == 0

    document = confirma(session, OPERATOR, [citire(EXPORT)], citire(EXTRAS), START, {}, ["mf.xls", "extras.xlsx"])
    assert (document.tip, document.stare, document.data) == ("INITIAL", "VALIDAT", START)
    assert len(document.linii) == 3
    marcela = session.scalar(select(Persoana).where(Persoana.nume == "HRITCU MARCELA"))
    inc = incadrare_la(session, marcela.id, START)
    assert (inc.locatie.denumire, inc.activitate.denumire) == ("Botosani", "Botosani (1Int)")
    assert session.scalar(select(Bun).where(Bun.nr_inventar == "3")).cont.sintetic == "303"
    intrare = session.scalar(select(Jurnal).where(Jurnal.actiune == "IMPORT_INITIAL"))
    assert json.loads(intrare.detalii_json)["repartizate"] == 3


def test_aceeasi_locatie_pentru_locatie_si_activitate(session):
    """„Trezorerie” e și locație, și activitate: două înregistrări independente."""
    _analiza(session, EXPORT, EXTRAS)
    confirma(session, OPERATOR, [citire(EXPORT)], citire(EXTRAS), START, {}, [])
    ana = session.scalar(select(Persoana).where(Persoana.nume == "CONSTANTIN ANA"))
    inc = incadrare_la(session, ana.id, START)
    assert inc.locatie.denumire == inc.activitate.denumire == "Trezorerie"


def test_consultarea_nu_importa(session):
    with pytest.raises(AccesInterzis):
        confirma(session, CONSULTARE, [citire(EXPORT)], citire(EXTRAS), START, {}, [])


# --- erori blocante (§9.3) ---

def test_eroare_nr_inventar_inexistent_in_export(session):
    raport = _analiza(session, EXPORT, [*EXTRAS, rand("999", "POP ION", nr_rand=9)])
    assert any("rândul 9" in e and "999 nu există în export" in e for e in raport.erori)


def test_eroare_tip_diferit(session):
    raport = _analiza(session, EXPORT, [rand("3", "POP ION", categorie="MF")])
    assert any("este MF în extras, dar OI în export" in e for e in raport.erori)


def test_eroare_aceeasi_persoana_cu_incadrari_diferite(session):
    raport = _analiza(session, EXPORT, [rand("1", "POP ION"), rand("2", "POP ION", locatie="Dorohoi")])
    assert any("POP ION" in e and "locații sau activități diferite" in e for e in raport.erori)
    raport = _analiza(session, EXPORT, [rand("1", "POP ION"), rand("2", "POP ION", activitate="Botosani (2C)")])
    assert any("locații sau activități diferite" in e for e in raport.erori)


def test_eroare_nr_inventar_duplicat_in_extras(session):
    raport = _analiza(session, EXPORT, [rand("1", "POP ION", nr_rand=2), rand("1", "ION POP", nr_rand=5)])
    assert any("de mai multe ori în extras (rândurile 2 și 5)" in e for e in raport.erori)


def test_eroare_duplicat_in_export(session):
    raport = _analiza(session, [*EXPORT, bun("1")], EXTRAS)
    assert any("de mai multe ori în export" in e for e in raport.erori)


def test_erorile_de_citire_sunt_blocante(session):
    raport = analizeaza(session, [RezultatCitire([], ["mf.xls, rândul 7: dată invalidă."])], citire([]), START)
    assert raport.erori[0] == "mf.xls, rândul 7: dată invalidă."
    assert not raport.poate_confirma


def test_import_doar_o_data(session):
    confirma(session, OPERATOR, [citire(EXPORT)], citire(EXTRAS), START, {}, [])
    raport = _analiza(session, EXPORT, EXTRAS)
    assert "Importul inițial a fost deja făcut." in raport.erori


def test_confirmarea_refuza_erorile(session):
    with pytest.raises(EroareValidare, match="erori blocante"):
        confirma(session, OPERATOR, [citire(EXPORT)], citire([rand("999", "X")]), START, {}, [])
    assert session.scalar(select(func.count()).select_from(Document)) == 0


# --- avertismente (§9.3) ---

def test_avertisment_bun_fara_persoana(session):
    raport = _analiza(session, [*EXPORT, bun("4"), bun("5", nr_doc_casare="12", data_casare=date(2024, 1, 1))],
                      EXTRAS)
    # Bunul casat și nerepartizat nu e semnalat: e situația normală.
    assert [m.split(" — ")[0] for m in raport.avertismente[AV_FARA_PERSOANA]] == ["4"]
    assert raport.poate_confirma
    confirma(session, OPERATOR, [citire([*EXPORT, bun("4")])], citire(EXTRAS), START, {}, [])
    neimpartit = session.scalar(select(Bun).where(Bun.nr_inventar == "4"))
    assert session.scalar(select(LinieDocument).where(LinieDocument.bun_id == neimpartit.id)) is None


def test_avertisment_nr_vechi_diferit_prioritate_export(session):
    export = [replace(EXPORT[0], nr_inventar_vechi="611388")]
    raport = _analiza(session, export, [rand("1", "POP ION", vechi="5184")])
    assert raport.avertismente[AV_NR_VECHI] == ["1: extras „5184”, export „611388”."]
    confirma(session, OPERATOR, [citire(export)], citire([rand("1", "POP ION", vechi="5184")]), START, {}, [])
    assert session.scalar(select(Bun.nr_inventar_vechi)) == "611388"


def test_avertisment_bun_casat_repartizat(session):
    export = [bun("1", nr_doc_casare="7", data_casare=date(2025, 3, 1))]
    raport = _analiza(session, export, [rand("1", "POP ION")])
    assert "01.03.2025" in raport.avertismente[AV_CASATE][0]


# --- nume foarte apropiate ---

def test_perechi_similare():
    perechi = perechi_similare([
        "AIONITOAIE CORNELIU", "AIONITOAIE CORNELIU VIRGIL et II", "NECHIFOR DAN", "NECHIFOR DAN ET2",
        "MIHAI CRSITINA", "MIHAI CRISTINA", "CRĂCIUN VIOREL", "CRACIUN VIOREL", "POP ION", "DELEANU BEATRICE-GETA",
    ])
    assert {(p.a, p.b) for p in perechi} == {
        ("AIONITOAIE CORNELIU", "AIONITOAIE CORNELIU VIRGIL et II"),
        ("NECHIFOR DAN", "NECHIFOR DAN ET2"),
        ("MIHAI CRISTINA", "MIHAI CRSITINA"),
        ("CRACIUN VIOREL", "CRĂCIUN VIOREL"),
    }


EXTRAS_APROPIATE = [rand("1", "AIONITOAIE CORNELIU"),
                    rand("3", "AIONITOAIE CORNELIU VIRGIL et II", "OI")]


def test_perechile_trebuie_decise(session):
    raport = _analiza(session, EXPORT, EXTRAS_APROPIATE)
    assert len(raport.nedecise) == 1 and not raport.poate_confirma
    with pytest.raises(EroareValidare, match="perechi"):
        confirma(session, OPERATOR, [citire(EXPORT)], citire(EXTRAS_APROPIATE), START, {}, [])


def test_decizie_gestiune_secundara(session):
    [pereche] = _analiza(session, EXPORT, EXTRAS_APROPIATE).perechi
    confirma(session, OPERATOR, [citire(EXPORT)], citire(EXTRAS_APROPIATE), START,
             {pereche.cheie: "B_SECUNDARA_A"}, [])
    secundara = session.scalar(select(Persoana).where(Persoana.nume == "AIONITOAIE CORNELIU VIRGIL et II"))
    assert secundara.titular.nume == "AIONITOAIE CORNELIU"
    assert secundara.nume_semnatura == "AIONITOAIE CORNELIU"


def test_decizie_unificare(session):
    [pereche] = _analiza(session, EXPORT, EXTRAS_APROPIATE).perechi
    confirma(session, OPERATOR, [citire(EXPORT)], citire(EXTRAS_APROPIATE), START, {pereche.cheie: "UNIFICA_A"}, [])
    [persoana] = session.scalars(select(Persoana)).all()
    assert persoana.nume == "AIONITOAIE CORNELIU"
    assert session.scalar(select(func.count()).select_from(LinieDocument)
                          .where(LinieDocument.persoana_la_id == persoana.id)) == 2


def test_unificarea_poate_crea_conflict_de_incadrare(session):
    extras = [rand("1", "NECHIFOR DAN"), rand("2", "NECHIFOR DAN ET2", locatie="Dorohoi")]
    [pereche] = _analiza(session, EXPORT, extras).perechi
    assert _analiza(session, EXPORT, extras, {pereche.cheie: "B_SECUNDARA_A"}).poate_confirma
    raport = _analiza(session, EXPORT, extras, {pereche.cheie: "UNIFICA_A"})
    assert any("locații sau activități diferite" in e for e in raport.erori)


def test_titular_pe_un_singur_nivel(session):
    export = [bun("1"), bun("2"), bun("3")]
    extras = [rand("1", "POP ION"), rand("2", "POP ION ET2"), rand("3", "POP ION ET2 BIS")]
    perechi = {(p.a, p.b): p.cheie for p in _analiza(session, export, extras).perechi}
    decizii = {perechi[("POP ION", "POP ION ET2")]: "B_SECUNDARA_A",
               perechi[("POP ION ET2", "POP ION ET2 BIS")]: "B_SECUNDARA_A",
               perechi[("POP ION", "POP ION ET2 BIS")]: "DIFERITE"}
    raport = _analiza(session, export, extras, decizii)
    assert any("este la rândul lui gestiune secundară" in e for e in raport.erori)


def test_nume_diferite_doar_prin_majuscule(session):
    extras = [rand("1", "Pop Ion"), rand("2", "POP ION")]
    [pereche] = _analiza(session, EXPORT, extras).perechi
    raport = _analiza(session, EXPORT, extras, {pereche.cheie: "DIFERITE"})
    assert any("doar prin majuscule" in e for e in raport.erori)


def test_baza_cu_persoane_existente_refuzata(session, persoana):
    persoana("CINEVA")
    raport = _analiza(session, EXPORT, EXTRAS)
    assert any("baza fără persoane" in e or "bază fără persoane" in e for e in raport.erori)


def test_locatie_existenta_inactiva(session, nom):
    from inventar.domain.nomenclatoare import seteaza_activ_nomenclator
    from inventar.models import Locatie

    seteaza_activ_nomenclator(session, OPERATOR, Locatie, nom["dorohoi"].id, False)
    raport = _analiza(session, EXPORT, [rand("1", "POP ION", locatie="DOROHOI")])
    assert any("Dorohoi" in e or "DOROHOI" in e for e in raport.erori)


def test_locatie_existenta_reutilizata(session, nom):
    confirma(session, OPERATOR, [citire(EXPORT)], citire([rand("1", "POP ION", locatie="botosani")]), START, {}, [])
    p = session.scalar(select(Persoana))
    assert incadrare_la(session, p.id, START).locatie_id == nom["botosani"].id


def test_toate_problemele_apar_intr_o_trecere(session):
    """Nume apropiate și încadrări diferite se raportează și pe rândurile cu alte erori."""
    extras = [rand("998", "AIONITOAIE CORNELIU"), rand("999", "AIONITOAIE CORNELIU VIRGIL et II", "OI"),
              rand("997", "POP ION"), rand("996", "POP ION", locatie="Dorohoi")]
    raport = _analiza(session, EXPORT, extras)
    assert len(raport.perechi) == 1
    assert any("POP ION" in e and "diferite" in e for e in raport.erori)
