import re
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import func, select

from inventar.importuri.mf_baza import RezultatCitire
from inventar.models import Document, LinieDocument, Persoana
from tests.importuri.test_import_initial import bun


def _xlsx(randuri) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Tip", "Locatia", "Activitatea", "Persoana", "NrInventar", "NrInventarVechi"])
    for r in randuri:
        ws.append(r)
    continut = BytesIO()
    wb.save(continut)
    return continut.getvalue()


def _incarca(client, extras: bytes):
    return client.post("/importuri/initial", data={
        "mf_baza": [(BytesIO(b"xls"), "MIJLOACE FIXE.xls")],
        "extras": (BytesIO(extras), "Imp_Ap_Existenta.xlsx"),
        "data_start": "2025-11-28",
    }, content_type="multipart/form-data")


def test_flux_import(client, session, creeaza, monkeypatch):
    monkeypatch.setattr("inventar.web.importuri.citeste_mf_baza",
                        lambda continut, fisier: RezultatCitire([bun("1"), bun("2")], []))
    creeaza("op", rol="OPERATOR")
    client.post("/autentificare", data={"username": "op", "parola": "parola123"})

    r = _incarca(client, _xlsx([
        ["MijloaceFixe", "Botosani", "Botosani (1Int)", "NECHIFOR DAN", 1, 0],
        ["MijloaceFixe", "Dorohoi", "Dorohoi", "NECHIFOR DAN ET2", 2, 0],
    ]))
    assert r.status_code == 302
    url = r.headers["Location"]

    pagina = client.get(url).get_data(as_text=True)
    assert "Nume foarte apropiate (1)" in pagina
    assert session.scalar(select(func.count()).select_from(Persoana)) == 0
    camp = re.search(r'name="(decizie_[0-9a-f]+)"', pagina).group(1)

    # Fără decizie, confirmarea e refuzată.
    r = client.post(url, data={"actiune": "confirma"})
    assert "Alegeți o variantă" in r.get_data(as_text=True)

    r = client.post(url, data={"actiune": "confirma", camp: "B_SECUNDARA_A"})
    assert r.status_code == 302
    assert session.scalar(select(Document.tip)) == "INITIAL"
    assert session.scalar(select(func.count()).select_from(LinieDocument)) == 2
    et2 = session.scalar(select(Persoana).where(Persoana.nume == "NECHIFOR DAN ET2"))
    assert et2.titular.nume == "NECHIFOR DAN"
    # Fișierele temporare se șterg, iar importul nu se mai poate repeta.
    assert client.get(url).status_code == 404
    assert "a fost făcut" in client.get("/importuri/initial").get_data(as_text=True)


def test_raport_cu_erori_nu_are_buton_de_confirmare(client, creeaza, monkeypatch):
    monkeypatch.setattr("inventar.web.importuri.citeste_mf_baza",
                        lambda continut, fisier: RezultatCitire([bun("1")], []))
    creeaza("op", rol="OPERATOR")
    client.post("/autentificare", data={"username": "op", "parola": "parola123"})
    r = _incarca(client, _xlsx([["ObiecteInventar", "Botosani", "Botosani (1Int)", "POP ION", 1, 0]]))
    pagina = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "1 erori blocante" in pagina
    assert 'value="confirma"' not in pagina


def test_raportul_altui_utilizator_interzis(client, creeaza, monkeypatch):
    monkeypatch.setattr("inventar.web.importuri.citeste_mf_baza",
                        lambda continut, fisier: RezultatCitire([bun("1")], []))
    creeaza("op", rol="OPERATOR")
    creeaza("op2", rol="OPERATOR")
    client.post("/autentificare", data={"username": "op", "parola": "parola123"})
    url = _incarca(client, _xlsx([["MijloaceFixe", "B", "B", "POP ION", 1, 0]])).headers["Location"]
    client.post("/deconectare")
    client.post("/autentificare", data={"username": "op2", "parola": "parola123"})
    assert client.get(url).status_code == 403
    assert client.get("/importuri/initial/nu-e-token").status_code == 404


def test_consultarea_nu_are_acces_la_import(client, creeaza):
    creeaza("cons", rol="CONSULTARE")
    client.post("/autentificare", data={"username": "cons", "parola": "parola123"})
    assert client.get("/importuri/initial").status_code == 403
