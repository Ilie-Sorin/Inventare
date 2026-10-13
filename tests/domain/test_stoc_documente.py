from datetime import date

import pytest
from sqlalchemy import select

from inventar.domain.comun import EroareValidare
from inventar.domain.documente import LinieNoua, anuleaza, salveaza_ciorna, urmatorul_numar, valideaza
from inventar.domain.stoc import bunuri_la_persoana, detinatori_la, nerepartizate, situatia_la
from inventar.drepturi import AccesInterzis
from inventar.models import Jurnal
from tests.conftest import CONSULTARE, OPERATOR

START = date(2025, 1, 1)
D1, D2, D3 = date(2025, 3, 1), date(2025, 6, 1), date(2025, 9, 1)


@pytest.fixture
def lume(session, persoana, bunuri, initial):
    """A are b1, b2; B are b3; b4 e nerepartizat."""
    a, b = persoana("A"), persoana("B")
    b1, b2, b3, b4 = bunuri("1", "2", "3", "4")
    initial(START, [(b1, a), (b2, a), (b3, b)])
    return {"a": a, "b": b, "b1": b1, "b2": b2, "b3": b3, "b4": b4}


def transfer(session, de_la, la, bunuri_, data, valideaza_acum=True, numar="1"):
    doc = salveaza_ciorna(session, OPERATOR, "TRANSFER", data, numar,
                          [LinieNoua(x.id, de_la.id, la.id) for x in bunuri_])
    return valideaza(session, OPERATOR, doc.id) if valideaza_acum else doc


def iesire(session, de_la, bunuri_, data, motiv="CASARE"):
    doc = salveaza_ciorna(session, OPERATOR, "IESIRE", data, "1",
                          [LinieNoua(x.id, de_la.id, None) for x in bunuri_], motiv_iesire=motiv)
    return valideaza(session, OPERATOR, doc.id)


def intrare(session, la, bunuri_, data):
    doc = salveaza_ciorna(session, OPERATOR, "INTRARE", data, "1", [LinieNoua(x.id, None, la.id) for x in bunuri_])
    return valideaza(session, OPERATOR, doc.id)


def detinator(session, bun, data):
    return detinatori_la(session, data, [bun.id]).get(bun.id, "nerepartizat")


# --- situația la o dată ---

def test_stoc_dupa_initial(session, lume):
    assert [x.nr_inventar for x in bunuri_la_persoana(session, lume["a"].id, START)] == ["1", "2"]
    assert detinator(session, lume["b1"], date(2024, 12, 31)) == "nerepartizat"
    assert [x.nr_inventar for x in nerepartizate(session, START)] == ["4"]


def test_stoc_dupa_transfer_iesire_intrare(session, lume):
    transfer(session, lume["a"], lume["b"], [lume["b1"]], D1)
    iesire(session, lume["b"], [lume["b3"]], D2)
    intrare(session, lume["a"], [lume["b4"]], D3)

    assert detinator(session, lume["b1"], D1 - date.resolution) == lume["a"].id
    assert detinator(session, lume["b1"], D1) == lume["b"].id
    assert detinator(session, lume["b3"], D2) is None  # ieșit
    assert detinator(session, lume["b4"], D2) == "nerepartizat"
    assert detinator(session, lume["b4"], D3) == lume["a"].id

    randuri = {r.bun_id: r for r in session.execute(situatia_la(D3))}
    assert set(randuri) == {lume["b1"].id, lume["b2"].id, lume["b4"].id}
    assert randuri[lume["b1"].id].persoana_id == lume["b"].id
    assert randuri[lume["b1"].id].locatie_id is not None


def test_ciorna_si_anulat_ignorate(session, lume):
    transfer(session, lume["a"], lume["b"], [lume["b1"]], D1, valideaza_acum=False)
    assert detinator(session, lume["b1"], D3) == lume["a"].id
    doc = transfer(session, lume["a"], lume["b"], [lume["b2"]], D1)
    anuleaza(session, OPERATOR, doc.id, "greșeală")
    assert detinator(session, lume["b2"], D3) == lume["a"].id


def test_aceeasi_data_ordonata_dupa_document(session, lume):
    transfer(session, lume["a"], lume["b"], [lume["b1"]], D1)
    transfer(session, lume["b"], lume["a"], [lume["b1"]], D1)
    assert detinator(session, lume["b1"], D1) == lume["a"].id


# --- reguli de validare ---

def test_data_inainte_de_initial(session, lume):
    with pytest.raises(EroareValidare, match="inventarului inițial"):
        salveaza_ciorna(session, OPERATOR, "TRANSFER", date(2024, 12, 31), "1",
                        [LinieNoua(lume["b1"].id, lume["a"].id, lume["b"].id)])


def test_bunul_nu_e_la_persoana_de_la(session, lume):
    doc = transfer(session, lume["b"], lume["a"], [lume["b1"]], D1, valideaza_acum=False)
    with pytest.raises(EroareValidare, match="nu se află la „B”"):
        valideaza(session, OPERATOR, doc.id)


def test_intrare_doar_pentru_bun_nerepartizat(session, lume):
    doc = salveaza_ciorna(session, OPERATOR, "INTRARE", D1, "1", [LinieNoua(lume["b1"].id, None, lume["b"].id)])
    with pytest.raises(EroareValidare, match="este deja repartizat"):
        valideaza(session, OPERATOR, doc.id)


def test_ordine_cronologica_pe_bun(session, lume):
    transfer(session, lume["a"], lume["b"], [lume["b1"]], D2)
    doc = transfer(session, lume["a"], lume["b"], [lume["b1"], lume["b2"]], D1, valideaza_acum=False)
    with pytest.raises(EroareValidare, match="mișcare validată ulterioară"):
        valideaza(session, OPERATOR, doc.id)


def test_ordine_cronologica_la_aceeasi_data(session, lume):
    """Ciorna creată prima (id mai mic) nu se mai validează după o mișcare din aceeași zi."""
    ciorna = transfer(session, lume["a"], lume["b"], [lume["b2"]], D1, valideaza_acum=False)
    transfer(session, lume["a"], lume["b"], [lume["b2"]], D1)
    with pytest.raises(EroareValidare, match="ulterioară"):
        valideaza(session, OPERATOR, ciorna.id)


def test_bun_iesit_nu_mai_poate_fi_miscat(session, lume):
    iesire(session, lume["a"], [lume["b1"]], D1)
    for doc in (
        salveaza_ciorna(session, OPERATOR, "TRANSFER", D2, "1", [LinieNoua(lume["b1"].id, lume["a"].id, lume["b"].id)]),
        salveaza_ciorna(session, OPERATOR, "INTRARE", D2, "1", [LinieNoua(lume["b1"].id, None, lume["b"].id)]),
    ):
        with pytest.raises(EroareValidare, match="a ieșit din evidență"):
            valideaza(session, OPERATOR, doc.id)


def test_destinatar_inactiv_sau_neincadrat(session, lume, persoana):
    nou = persoana("C", de_la=D3)  # încadrat abia de la D3
    doc = transfer(session, lume["a"], nou, [lume["b1"]], D1, valideaza_acum=False)
    with pytest.raises(EroareValidare, match="nu are încadrare"):
        valideaza(session, OPERATOR, doc.id)


@pytest.mark.parametrize("tip, de_la, la, motiv, mesaj", [
    ("TRANSFER", "a", "a", None, "aceeași persoană"),
    ("TRANSFER", None, "b", None, "predă"),
    ("IESIRE", "a", None, None, "Motivul ieșirii"),
    ("IESIRE", "a", "b", "CASARE", "nu are destinatar"),
    ("INTRARE", "a", "b", None, "nu are predător"),
    ("INITIAL", None, "b", None, "Tip de document"),
])
def test_forma_liniilor(session, lume, tip, de_la, la, motiv, mesaj):
    linie = LinieNoua(lume["b1"].id, lume[de_la].id if de_la else None, lume[la].id if la else None)
    with pytest.raises(EroareValidare, match=mesaj):
        salveaza_ciorna(session, OPERATOR, tip, D1, "1", [linie], motiv_iesire=motiv)


def test_bun_de_doua_ori_in_document(session, lume):
    linie = LinieNoua(lume["b1"].id, lume["a"].id, lume["b"].id)
    with pytest.raises(EroareValidare, match="de mai multe ori"):
        salveaza_ciorna(session, OPERATOR, "TRANSFER", D1, "1", [linie, linie])


def test_document_fara_linii(session, lume):
    with pytest.raises(EroareValidare, match="cel puțin un bun"):
        salveaza_ciorna(session, OPERATOR, "TRANSFER", D1, "1", [])


def test_consultarea_nu_creeaza_documente(session, lume):
    with pytest.raises(AccesInterzis):
        salveaza_ciorna(session, CONSULTARE, "TRANSFER", D1, "1", [LinieNoua(lume["b1"].id, lume["a"].id, lume["b"].id)])


def test_modificare_ciorna_si_numerotare(session, lume):
    assert urmatorul_numar(session, "TRANSFER", 2025) == "1"
    doc = transfer(session, lume["a"], lume["b"], [lume["b1"]], D1, valideaza_acum=False, numar="7")
    assert urmatorul_numar(session, "TRANSFER", 2025) == "8"
    salveaza_ciorna(session, OPERATOR, "TRANSFER", D2, "7", [LinieNoua(lume["b2"].id, lume["a"].id, lume["b"].id)],
                    document_id=doc.id)
    assert [linie.bun_id for linie in doc.linii] == [lume["b2"].id]
    valideaza(session, OPERATOR, doc.id)
    with pytest.raises(EroareValidare, match="Doar ciornele"):
        salveaza_ciorna(session, OPERATOR, "TRANSFER", D2, "7", [LinieNoua(lume["b1"].id, lume["a"].id,
                                                                            lume["b"].id)], document_id=doc.id)


# --- anulare ---

def test_anulare_blocata_de_miscari_ulterioare(session, lume):
    primul = transfer(session, lume["a"], lume["b"], [lume["b1"]], D1)
    al_doilea = transfer(session, lume["b"], lume["a"], [lume["b1"]], D2)
    with pytest.raises(EroareValidare, match="ulterioare"):
        anuleaza(session, OPERATOR, primul.id, "greșeală")
    anuleaza(session, OPERATOR, al_doilea.id, "greșeală")
    anuleaza(session, OPERATOR, primul.id, "greșeală")
    assert detinator(session, lume["b1"], D3) == lume["a"].id


def test_anulare_cere_motiv_si_scrie_in_jurnal(session, lume):
    doc = transfer(session, lume["a"], lume["b"], [lume["b1"]], D1)
    with pytest.raises(EroareValidare, match="Motivul"):
        anuleaza(session, OPERATOR, doc.id, "  ")
    anuleaza(session, OPERATOR, doc.id, "bon greșit")
    assert doc.stare == "ANULAT" and doc.motiv_anulare == "bon greșit"
    intrare_jurnal = session.scalars(select(Jurnal).order_by(Jurnal.id.desc())).first()
    assert intrare_jurnal.actiune == "DOCUMENT_ANULAT" and "bon greșit" in intrare_jurnal.detalii_json


def test_initialul_nu_se_anuleaza(session, lume):
    from inventar.models import Document

    doc = session.scalar(select(Document).where(Document.tip == "INITIAL"))
    with pytest.raises(EroareValidare, match="inițial"):
        anuleaza(session, OPERATOR, doc.id, "x")


def test_anulat_nu_se_mai_valideaza(session, lume):
    doc = transfer(session, lume["a"], lume["b"], [lume["b1"]], D1, valideaza_acum=False)
    anuleaza(session, OPERATOR, doc.id, "renunț")
    with pytest.raises(EroareValidare, match="ciornele"):
        valideaza(session, OPERATOR, doc.id)


def test_transfer_in_masa(session, lume):
    toate = bunuri_la_persoana(session, lume["a"].id, D1)
    transfer(session, lume["a"], lume["b"], toate, D1)
    assert bunuri_la_persoana(session, lume["a"].id, D1) == []
    assert len(bunuri_la_persoana(session, lume["b"].id, D1)) == 3


def test_persoana_cu_bunuri_nu_se_dezactiveaza(session, lume):
    from inventar.domain.persoane import seteaza_activ_persoana

    with pytest.raises(EroareValidare, match="are în primire"):
        seteaza_activ_persoana(session, OPERATOR, lume["a"].id, False)
    transfer(session, lume["a"], lume["b"], [lume["b1"], lume["b2"]], D1)
    seteaza_activ_persoana(session, OPERATOR, lume["a"].id, False)
