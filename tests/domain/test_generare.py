import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from inventar.domain.comisii import MembruNou, creeaza_comisie
from inventar.domain.comun import EroareValidare
from inventar.domain.documente import LinieNoua, anuleaza, salveaza_ciorna, valideaza
from inventar.domain.generare import (
    Perimetru,
    avertismente,
    blocheaza,
    deblocheaza,
    genereaza,
    regenereaza,
    sterge,
)
from inventar.domain.incadrare import corecteaza_ultima_incadrare
from inventar.domain.schimbare_incadrare import schimba_incadrarea
from inventar.drepturi import AccesInterzis
from inventar.models import Inventar, InventarLinie, Jurnal
from tests.conftest import ADMIN_CLI, OPERATOR

START = date(2025, 1, 1)
D = date(2025, 11, 28)


@pytest.fixture
def lume(session, persoana, bunuri, initial, nom):
    marcela = persoana("HRITCU MARCELA")
    dan = persoana("NECHIFOR DAN", locatie="dorohoi", activitate="2c")
    et2 = persoana("NECHIFOR DAN ET2", locatie="trezorerie_loc", activitate="trezorerie_act", titular_id=dan.id)
    mf = bunuri("1", "2", "3", cont="213.01", pret="3886.25")
    oi = bunuri("4", "5", categorie="OI", cont="303.02.00.04", pret="145.00",
                data_amortizare_integrala=date(2020, 1, 1))
    [nerep] = bunuri("6")
    initial(START, [(mf[0], marcela), (mf[1], marcela), (mf[2], marcela), (oi[0], dan), (oi[1], et2)])
    creeaza_comisie(session, OPERATOR, nom["botosani"].id, START, None,
                    [MembruNou("POPESCU ANA", "PRESEDINTE"), MembruNou("IONESCU ŞTEFAN", "MEMBRU")])
    return {"marcela": marcela, "dan": dan, "et2": et2, "mf": mf, "oi": oi, "nerep": nerep, "nom": nom}


def linii(session, inventar) -> list[InventarLinie]:
    return list(session.scalars(select(InventarLinie).where(InventarLinie.inventar_id == inventar.id)
                                .order_by(InventarLinie.nr_inventar)))


def transfer(session, de_la, la, bun, data):
    doc = salveaza_ciorna(session, OPERATOR, "TRANSFER", data, "1", [LinieNoua(bun.id, de_la.id, la.id)])
    return valideaza(session, OPERATOR, doc.id)


def test_generare_copiaza_campurile(session, lume):
    inv = genereaza(session, OPERATOR, D, Perimetru())
    assert (inv.stare, inv.nr_linii) == ("GENERAT", 5)
    randuri = linii(session, inv)
    r = randuri[0]
    assert (r.gestiune, r.titular, r.locatie, r.activitate, r.cont, r.cont_sintetic, r.categorie) == (
        "HRITCU MARCELA", "HRITCU MARCELA", "Botosani", "Botosani (1Int)", "213.01", "213", "MF")
    assert sum(x.pret for x in randuri if x.persoana_id == lume["marcela"].id) == Decimal("11658.75")
    secundara = next(x for x in randuri if x.nr_inventar == "5")
    assert (secundara.gestiune, secundara.titular, secundara.titular_id) == (
        "NECHIFOR DAN ET2", "NECHIFOR DAN", lume["dan"].id)
    assert secundara.data_amortizare_integrala == date(2020, 1, 1)
    # Comisiile se copiază pentru fiecare locație din instantaneu, cu sau fără comisie definită.
    comisii = {c.locatie: json.loads(c.membri_json) for c in inv.comisii}
    assert comisii["Botosani"] == [{"nume": "POPESCU ANA", "calitate": "PRESEDINTE"},
                                   {"nume": "IONESCU ŞTEFAN", "calitate": "MEMBRU"}]
    assert comisii["Dorohoi"] == []


@pytest.mark.parametrize("perimetru, asteptate", [
    (Perimetru(categorii=("OI",)), {"4", "5"}),
    (Perimetru(conturi=("213",)), {"1", "2", "3"}),
    (Perimetru(locatii=("dorohoi",)), {"4"}),
    (Perimetru(activitati=("trezorerie_act",)), {"5"}),
    (Perimetru(persoane=("dan",), categorii=("OI",)), {"4"}),
])
def test_perimetru(session, lume, perimetru, asteptate):
    # Fixture-ul folosește chei; le traducem în id-uri reale.
    def ids(chei, sursa):
        return tuple(sursa[k].id for k in chei)
    p = Perimetru(
        locatii=ids(perimetru.locatii, lume["nom"]), activitati=ids(perimetru.activitati, lume["nom"]),
        persoane=ids(perimetru.persoane, lume), categorii=perimetru.categorii, conturi=perimetru.conturi,
    )
    inv = genereaza(session, OPERATOR, D, p)
    assert {x.nr_inventar for x in linii(session, inv)} == asteptate


def test_perimetru_grup(session, lume):
    from inventar.domain.nomenclatoare import creeaza_grup

    grup = creeaza_grup(session, OPERATOR, "G", [lume["et2"].id])
    inv = genereaza(session, OPERATOR, D, Perimetru(grupuri=(grup.id,)))
    assert [x.nr_inventar for x in linii(session, inv)] == ["5"]


def test_perimetru_normalizat_si_unicitate(session, lume):
    a = Perimetru(categorii=("OI", "MF"), locatii=(3, 1, 1))
    b = Perimetru(categorii=("MF", "OI"), locatii=(1, 3))
    assert a.json() == b.json()
    assert Perimetru.din_json(a.json()) == b.normalizat()
    genereaza(session, OPERATOR, D, Perimetru())
    with pytest.raises(EroareValidare, match="Există deja"):
        genereaza(session, OPERATOR, D, Perimetru())
    genereaza(session, OPERATOR, D, Perimetru(categorii=("MF",)))  # alt perimetru: permis


def test_perimetru_invalid(session, lume):
    with pytest.raises(EroareValidare):
        genereaza(session, OPERATOR, D, Perimetru(categorii=("XX",)))
    with pytest.raises(EroareValidare):
        genereaza(session, OPERATOR, D, Perimetru(locatii=(999,)))


def test_avertismente(session, lume):
    from datetime import datetime

    from inventar.models import Document

    mesaje = avertismente(session, D, Perimetru())
    assert any("1 bunuri nerepartizate" in m for m in mesaje)
    assert any("Dorohoi" in m and "comisie" in m for m in mesaje)
    assert not any("export" in m for m in mesaje)  # exportul a fost încărcat după D

    session.scalar(select(Document).where(Document.tip == "INITIAL")).creat_la = datetime(2025, 6, 1)
    session.commit()
    assert any("anterioară datei" in m for m in avertismente(session, D, Perimetru()))
    # Bunurile nerepartizate se numără doar în categoriile din perimetru.
    assert not any("nerepartizate" in m for m in avertismente(session, D, Perimetru(categorii=("OI",))))


# --- imuabilitatea instantaneului (§13) ---

def test_document_nou_marcheaza_neactualizat_dar_nu_si_blocat(session, lume):
    generat = genereaza(session, OPERATOR, D, Perimetru())
    blocat = genereaza(session, OPERATOR, D, Perimetru(categorii=("MF",)))
    blocheaza(session, OPERATOR, blocat.id)
    inainte = [(x.nr_inventar, x.gestiune, x.pret) for x in linii(session, blocat)]

    transfer(session, lume["marcela"], lume["dan"], lume["mf"][0], date(2025, 6, 1))

    assert generat.stare == "NEACTUALIZAT"
    assert blocat.stare == "BLOCAT"
    assert [(x.nr_inventar, x.gestiune, x.pret) for x in linii(session, blocat)] == inainte
    # Instantaneul GENERAT nu se modifică nici el singur; doar regenerarea îl schimbă.
    assert next(x for x in linii(session, generat) if x.nr_inventar == "1").gestiune == "HRITCU MARCELA"


def test_document_ulterior_datei_nu_afecteaza(session, lume):
    inv = genereaza(session, OPERATOR, D, Perimetru())
    transfer(session, lume["marcela"], lume["dan"], lume["mf"][0], date(2025, 12, 1))
    assert inv.stare == "GENERAT"


def test_anularea_marcheaza_neactualizat(session, lume):
    doc = transfer(session, lume["marcela"], lume["dan"], lume["mf"][0], date(2025, 6, 1))
    inv = genereaza(session, OPERATOR, D, Perimetru())
    anuleaza(session, OPERATOR, doc.id, "greșeală")
    assert inv.stare == "NEACTUALIZAT"


def test_ciorna_nu_marcheaza(session, lume):
    inv = genereaza(session, OPERATOR, D, Perimetru())
    salveaza_ciorna(session, OPERATOR, "TRANSFER", date(2025, 6, 1), "1",
                    [LinieNoua(lume["mf"][0].id, lume["marcela"].id, lume["dan"].id)])
    assert inv.stare == "GENERAT"


def test_schimbarea_si_corectarea_incadrarii_marcheaza(session, lume):
    nom = lume["nom"]
    inv = genereaza(session, OPERATOR, D, Perimetru())
    schimba_incadrarea(session, OPERATOR, lume["marcela"].id, nom["dorohoi"].id, nom["1int"].id,
                       date(2025, 6, 1), None)
    assert inv.stare == "NEACTUALIZAT"

    regenereaza(session, OPERATOR, inv.id)
    initiala = lume["dan"].incadrari[0]
    corecteaza_ultima_incadrare(session, OPERATOR, initiala.id, nom["botosani"].id, nom["2c"].id, START, None)
    assert inv.stare == "NEACTUALIZAT"


def test_regenerare(session, lume):
    inv = genereaza(session, OPERATOR, D, Perimetru())
    transfer(session, lume["marcela"], lume["dan"], lume["mf"][0], date(2025, 6, 1))
    doc_intrare = salveaza_ciorna(session, OPERATOR, "INTRARE", date(2025, 6, 1), "1",
                                  [LinieNoua(lume["nerep"].id, None, lume["dan"].id)])
    valideaza(session, OPERATOR, doc_intrare.id)
    id_vechi = inv.id

    inv = regenereaza(session, OPERATOR, inv.id)
    assert (inv.id, inv.stare, inv.nr_linii) == (id_vechi, "GENERAT", 6)
    assert next(x for x in linii(session, inv) if x.nr_inventar == "1").gestiune == "NECHIFOR DAN"
    intrare = session.scalars(select(Jurnal).where(Jurnal.actiune == "INVENTAR_REGENERAT")).one()
    detalii = json.loads(intrare.detalii_json)
    assert (detalii["linii_inainte"], detalii["linii_dupa"]) == (5, 6)


def test_blocare_deblocare_stergere(session, lume):
    inv = genereaza(session, OPERATOR, D, Perimetru())
    blocheaza(session, OPERATOR, inv.id)
    with pytest.raises(EroareValidare, match="blocat"):
        sterge(session, OPERATOR, inv.id)
    with pytest.raises(EroareValidare, match="blocat"):
        regenereaza(session, OPERATOR, inv.id)
    with pytest.raises(AccesInterzis):
        deblocheaza(session, OPERATOR, inv.id, "corectură")
    with pytest.raises(EroareValidare, match="Motivul"):
        deblocheaza(session, ADMIN_CLI, inv.id, " ")
    deblocheaza(session, ADMIN_CLI, inv.id, "corectură")
    # După deblocare instantaneul trebuie revăzut: nu se reblochează fără regenerare.
    assert (inv.stare, inv.motiv_deblocare) == ("NEACTUALIZAT", "corectură")
    with pytest.raises(EroareValidare, match="GENERAT"):
        blocheaza(session, OPERATOR, inv.id)
    sterge(session, OPERATOR, inv.id)
    assert session.scalar(select(func.count()).select_from(Inventar)) == 0
    assert session.scalar(select(func.count()).select_from(InventarLinie)) == 0
    actiuni = list(session.scalars(select(Jurnal.actiune).where(Jurnal.actiune.like("INVENTAR_%")).order_by(Jurnal.id)))
    assert actiuni == ["INVENTAR_GENERAT", "INVENTAR_BLOCAT", "INVENTAR_DEBLOCAT", "INVENTAR_STERS"]
