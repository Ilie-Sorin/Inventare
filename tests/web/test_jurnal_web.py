import csv
from io import StringIO

from sqlalchemy import select

from inventar.models import Jurnal


def _login(client, nume, parola="parola123"):
    client.post("/deconectare")
    return client.post("/autentificare", data={"username": nume, "parola": parola})


def test_consultare_si_filtre(client, creeaza):
    creeaza("admin")
    creeaza("op", rol="OPERATOR")
    _login(client, "op", "gresita")
    _login(client, "admin")
    pagina = client.get("/admin/jurnal").get_data(as_text=True)
    assert "AUTENTIFICARE" in pagina and "ESEC" in pagina and "UTILIZATOR_CREAT" in pagina

    pagina = client.get("/admin/jurnal?rezultat=ESEC").get_data(as_text=True)
    assert "1 înregistrări" in pagina and "date greșite" in pagina
    pagina = client.get("/admin/jurnal?actiune=UTILIZATOR_CREAT&text=OPERATOR").get_data(as_text=True)
    assert "1 înregistrări" in pagina


def test_export_csv(client, session, creeaza):
    creeaza("admin")
    _login(client, "admin")
    r = client.get("/admin/jurnal.csv?actiune=AUTENTIFICARE")
    assert "attachment" in r.headers["Content-Disposition"]
    randuri = list(csv.reader(StringIO(r.data.decode("utf-8-sig")), delimiter=";"))
    assert randuri[0][4] == "Acțiune" and all(rand[4] == "AUTENTIFICARE" for rand in randuri[1:])
    # Exportul jurnalului e el însuși înregistrat.
    assert session.scalar(select(Jurnal.actiune).order_by(Jurnal.id.desc())) == "EXPORT_JURNAL"


def test_doar_administratorul(client, creeaza):
    creeaza("op", rol="OPERATOR")
    _login(client, "op")
    assert client.get("/admin/jurnal").status_code == 403
    assert client.get("/admin/jurnal.csv").status_code == 403
