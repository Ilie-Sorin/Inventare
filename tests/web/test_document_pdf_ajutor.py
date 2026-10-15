"""Bonul de mișcare (PDF) și pagina de ajutor."""
from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from inventar.models import Document, Jurnal

START = date(2025, 1, 1)


def _text(continut: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(continut)).pages)


@pytest.fixture
def lume(client, creeaza, persoana, bunuri, initial):
    a, b = persoana("POP ANA"), persoana("ION VASILE", locatie="dorohoi", activitate="2c")
    b1, b2 = bunuri("101", "102", pret="1000.50", serie="SN77")
    initial(START, [(b1, a), (b2, a)])
    creeaza("op", rol="OPERATOR")
    client.post("/autentificare", data={"username": "op", "parola": "parola123"})
    return {"a": a, "b": b, "b1": b1, "b2": b2}


def _transfer(client, lume, actiune: str) -> None:
    client.post("/documente/nou/TRANSFER", data={
        "data": "2025-03-01", "numar": "5", "persoana_de_la_id": lume["a"].id, "persoana_la_id": lume["b"].id,
        "bunuri": [lume["b1"].id, lume["b2"].id], actiune: "1",
    })


def test_bon_de_miscare_pdf(client, session, lume):
    _transfer(client, lume, "valideaza")
    doc = session.scalar(select(Document).where(Document.tip == "TRANSFER"))
    r = client.get(f"/documente/{doc.id}/pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    text = _text(r.data)
    for asteptat in ("BON DE MIȘCARE - TRANSFER", "nr. 5 din 01.03.2025", "POP ANA", "ION VASILE", "Dorohoi",
                     "101", "SN77", "2001,00", "Pagina 1 din 1", "Predă", "Primește"):
        assert asteptat in text, asteptat
    assert session.scalar(select(Jurnal).where(Jurnal.actiune == "PDF_DOCUMENT")) is not None


def test_ciorna_nu_se_tipareste(client, session, lume):
    _transfer(client, lume, "salveaza")
    doc = session.scalar(select(Document).where(Document.tip == "TRANSFER"))
    r = client.get(f"/documente/{doc.id}/pdf", follow_redirects=True)
    assert "numai un document validat" in r.get_data(as_text=True)
    assert "Tipărește PDF" not in client.get(f"/documente/{doc.id}").get_data(as_text=True)


def test_butonul_apare_la_validat(client, session, lume):
    _transfer(client, lume, "valideaza")
    doc = session.scalar(select(Document).where(Document.tip == "TRANSFER"))
    assert "Tipărește PDF" in client.get(f"/documente/{doc.id}").get_data(as_text=True)


def test_pagina_de_ajutor_si_meniu(client, lume):
    pagina = client.get("/ajutor").get_data(as_text=True)
    assert "Manual de utilizare" in pagina and "Bonul de mișcare" in pagina
    assert 'href="/ajutor"' in client.get("/").get_data(as_text=True)


def test_ajutorul_cere_autentificare(client):
    assert client.get("/ajutor").status_code == 302
