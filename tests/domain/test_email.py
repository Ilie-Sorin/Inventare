"""Trimiterea pe e-mail, testată pe un server SMTP local (aiosmtpd)."""
import socket
from datetime import date
from email import message_from_bytes
from email.policy import default
from io import BytesIO

import pytest
from aiosmtpd.controller import Controller
from pypdf import PdfReader
from sqlalchemy import select

from inventar.domain.comun import EroareValidare
from inventar.domain.generare import Perimetru, genereaza
from inventar.domain.sabloane import salveaza_sablon
from inventar.email.smtp import citeste_smtp, salveaza_smtp
from inventar.email.trimitere import porneste, pregateste_retrimiterea, previzualizare, trimite_lot, trimite_test
from inventar.models import Jurnal, Setare, TrimitereEmail
from tests.conftest import ADMIN_CLI, OPERATOR


def port_liber() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Colector:
    def __init__(self):
        self.mesaje = []

    async def handle_DATA(self, server, session, envelope):
        self.mesaje.append(message_from_bytes(envelope.content, policy=default))
        return "250 OK"


@pytest.fixture
def smtp_local():
    colector = Colector()
    port = port_liber()
    controller = Controller(colector, hostname="127.0.0.1", port=port)
    controller.start()
    yield colector, port
    controller.stop()


def configureaza(session, tmp_path, port):
    salveaza_smtp(session, ADMIN_CLI, tmp_path, server="127.0.0.1", port=port, securitate="niciuna",
                  utilizator="", parola=None, sterge_parola=False, expeditor="inventar@exemplu.ro",
                  nume_expeditor="Comisia de inventariere")


@pytest.fixture
def lume(session, persoana, bunuri, initial):
    dan = persoana("NECHIFOR DAN", email="dan@exemplu.ro")
    et2 = persoana("NECHIFOR DAN ET2", locatie="dorohoi", activitate="2c", titular_id=dan.id)
    ana = persoana("ANA FĂRĂ ADRESĂ")
    ion = persoana("ION POP", email="ion@exemplu.ro")
    [m1] = bunuri("1", cont="213.01", pret="100.00")
    [m2] = bunuri("2", cont="213.01", pret="200.00")
    [o1] = bunuri("3", categorie="OI", cont="303.02", pret="10.00")
    [m3] = bunuri("4", cont="213.01", pret="5.00")
    [m4] = bunuri("5", cont="213.01", pret="7.00")
    initial(date(2025, 1, 1), [(m1, dan), (o1, dan), (m2, et2), (m3, ana), (m4, ion)])
    inventar = genereaza(session, OPERATOR, date(2025, 11, 28), Perimetru())
    return {"inv": inventar, "dan": dan, "et2": et2, "ion": ion}


def test_previzualizare_un_mesaj_pe_titular(session, lume):
    p = previzualizare(session, lume["inv"].id)
    assert [(d.nume, d.adresa) for d in p.destinatari] == [("ION POP", "ion@exemplu.ro"),
                                                           ("NECHIFOR DAN", "dan@exemplu.ro")]
    dan = p.destinatari[1]
    assert dan.gestiuni == ["NECHIFOR DAN", "NECHIFOR DAN ET2"]  # ordinea tirajului: Botosani, apoi Dorohoi
    # Pe gestiune × categorie: lista, declarația de început și cea de sfârșit.
    assert [a["fisier"] for a in dan.atasamente] == [
        "Inventar_2025-11-28_NECHIFOR_DAN_MF.pdf", "Declaratii_inceput_2025-11-28_NECHIFOR_DAN_MF.pdf",
        "Declaratii_sfarsit_2025-11-28_NECHIFOR_DAN_MF.pdf",
        "Inventar_2025-11-28_NECHIFOR_DAN_OI.pdf", "Declaratii_inceput_2025-11-28_NECHIFOR_DAN_OI.pdf",
        "Declaratii_sfarsit_2025-11-28_NECHIFOR_DAN_OI.pdf",
        "Inventar_2025-11-28_NECHIFOR_DAN_ET2_MF.pdf", "Declaratii_inceput_2025-11-28_NECHIFOR_DAN_ET2_MF.pdf",
        "Declaratii_sfarsit_2025-11-28_NECHIFOR_DAN_ET2_MF.pdf"]
    assert [d.nume for d in p.fara_adresa] == ["ANA FĂRĂ ADRESĂ"]
    # Filtrul de listare se aplică și aici.
    assert [d.nume for d in previzualizare(session, lume["inv"].id, Perimetru(categorii=("OI",))).destinatari] == [
        "NECHIFOR DAN"]


def test_trimitere_completa(session, lume, smtp_local, tmp_path):
    colector, port = smtp_local
    configureaza(session, tmp_path, port)
    lot = porneste(session, OPERATOR, lume["inv"].id, tmp_path)
    assert [r.stare for r in session.scalars(select(TrimitereEmail))] == ["IN_ASTEPTARE"] * 2

    assert trimite_lot(session, OPERATOR, lot, tmp_path) == (2, 0)
    assert len(colector.mesaje) == 2
    mesaj = next(m for m in colector.mesaje if m["To"] == "dan@exemplu.ro")
    assert mesaj["Subject"] == "Liste de inventariere la data de 28.11.2025"
    assert "Comisia de inventariere" in mesaj["From"]
    corp = mesaj.get_body(preferencelist=("plain",)).get_content()
    assert "Bună ziua, NECHIFOR DAN," in corp and "Botosani, Dorohoi" in corp
    atasamente = {a.get_filename(): a.get_content() for a in mesaj.iter_attachments()}
    assert len(atasamente) == 9

    def text(fisier: str) -> str:
        return PdfReader(BytesIO(atasamente[fisier])).pages[0].extract_text()

    lista = text("Inventar_2025-11-28_NECHIFOR_DAN_ET2_MF.pdf")
    assert "NECHIFOR DAN ET2" in lista and "200,00" in lista and "Pagina 1 din 1" in lista
    inceput = text("Declaratii_inceput_2025-11-28_NECHIFOR_DAN_ET2_MF.pdf")
    assert "DECLARAŢIE DE INVENTAR" in inceput and "Subsemnatul NECHIFOR DAN," in inceput
    assert "gestiunea NECHIFOR DAN ET2" in inceput
    assert "DECLARAŢIE DE SFÂRŞIT DE INVENTAR" in text("Declaratii_sfarsit_2025-11-28_NECHIFOR_DAN_OI.pdf")
    assert all(r.stare == "TRIMIS" and r.trimis_la for r in session.scalars(select(TrimitereEmail)))
    actiuni = list(session.scalars(select(Jurnal.actiune).where(Jurnal.actiune.like("EMAIL_%")).order_by(Jurnal.id)))
    assert actiuni == ["EMAIL_LOT", "EMAIL_TRIMIS", "EMAIL_TRIMIS"]


def test_server_indisponibil_apoi_retrimitere(session, lume, tmp_path):
    port = port_liber()  # nimeni nu ascultă aici
    configureaza(session, tmp_path, port)
    lot = porneste(session, OPERATOR, lume["inv"].id, tmp_path)
    assert trimite_lot(session, OPERATOR, lot, tmp_path) == (0, 2)
    randuri = list(session.scalars(select(TrimitereEmail)))
    assert all(r.stare == "EROARE" and "Connection" in r.eroare for r in randuri)

    colector = Colector()
    controller = Controller(colector, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        assert pregateste_retrimiterea(session, OPERATOR, lot, include_intrerupte=False) == 2
        assert trimite_lot(session, OPERATOR, lot, tmp_path) == (2, 0)
    finally:
        controller.stop()
    assert len(colector.mesaje) == 2
    with pytest.raises(EroareValidare, match="cu eroare"):
        pregateste_retrimiterea(session, OPERATOR, lot, include_intrerupte=False)


def test_retrimitere_doar_la_cei_cu_eroare(session, lume, smtp_local, tmp_path):
    colector, port = smtp_local
    configureaza(session, tmp_path, port)
    lot = porneste(session, OPERATOR, lume["inv"].id, tmp_path)
    trimite_lot(session, OPERATOR, lot, tmp_path)
    primul = session.scalars(select(TrimitereEmail)).first()
    primul.stare, primul.eroare = "EROARE", "simulat"
    session.commit()
    assert pregateste_retrimiterea(session, OPERATOR, lot, include_intrerupte=False) == 1
    trimite_lot(session, OPERATOR, lot, tmp_path)
    assert len(colector.mesaje) == 3


def test_fara_smtp_sau_fara_adrese(session, lume, tmp_path):
    with pytest.raises(EroareValidare, match="SMTP"):
        porneste(session, OPERATOR, lume["inv"].id, tmp_path)
    configureaza(session, tmp_path, 25)
    with pytest.raises(EroareValidare, match="adresă"):
        porneste(session, OPERATOR, lume["inv"].id, tmp_path, Perimetru(conturi=("999",)))


def test_inventar_neactualizat(session, lume, tmp_path):
    lume["inv"].stare = "NEACTUALIZAT"
    session.commit()
    with pytest.raises(EroareValidare, match="regenerați"):
        previzualizare(session, lume["inv"].id)


def test_parola_smtp_criptata(session, tmp_path):
    salveaza_smtp(session, ADMIN_CLI, tmp_path, server="smtp.exemplu.ro", port=587, securitate="starttls",
                  utilizator="u", parola="secretă!", sterge_parola=False, expeditor="a@exemplu.ro", nume_expeditor="")
    stocat = session.get(Setare, "smtp_parola").valoare
    assert "secret" not in stocat and (tmp_path / "secret.key").exists()
    assert citeste_smtp(session, tmp_path).parola == "secretă!"
    # Câmpul gol păstrează parola; ștergerea explicită o golește.
    salveaza_smtp(session, ADMIN_CLI, tmp_path, server="smtp.exemplu.ro", port=587, securitate="starttls",
                  utilizator="u", parola="", sterge_parola=False, expeditor="a@exemplu.ro", nume_expeditor="")
    assert citeste_smtp(session, tmp_path).parola == "secretă!"
    salveaza_smtp(session, ADMIN_CLI, tmp_path, server="smtp.exemplu.ro", port=587, securitate="starttls",
                  utilizator="u", parola=None, sterge_parola=True, expeditor="a@exemplu.ro", nume_expeditor="")
    assert citeste_smtp(session, tmp_path).parola == ""
    jurnale = " ".join(session.scalars(select(Jurnal.detalii_json)))
    assert "secret" not in jurnale


def test_setari_smtp_doar_admin_si_validate(session, tmp_path):
    from inventar.drepturi import AccesInterzis

    with pytest.raises(AccesInterzis):
        salveaza_smtp(session, OPERATOR, tmp_path, server="x", port=25, securitate="niciuna", utilizator="",
                      parola=None, sterge_parola=False, expeditor="a@b.ro", nume_expeditor="")
    with pytest.raises(EroareValidare, match="expeditorului"):
        salveaza_smtp(session, ADMIN_CLI, tmp_path, server="x", port=25, securitate="niciuna", utilizator="",
                      parola=None, sterge_parola=False, expeditor="nu-e-adresa", nume_expeditor="")


def test_sablon_email_cu_camp_necunoscut(session):
    with pytest.raises(EroareValidare, match="nme"):
        salveaza_sablon(session, ADMIN_CLI, "email_inventar", "Liste {data}", "Bună ziua, {nme}")
    salveaza_sablon(session, ADMIN_CLI, "email_inventar", "Liste {data}", "Stimate {nume}, {{acolade}}")


def test_mesaj_de_proba(session, smtp_local, tmp_path):
    colector, port = smtp_local
    configureaza(session, tmp_path, port)
    trimite_test(session, ADMIN_CLI, tmp_path, "admin@exemplu.ro")
    assert colector.mesaje[0]["To"] == "admin@exemplu.ro"
