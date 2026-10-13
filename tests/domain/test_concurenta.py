"""Doi operatori validează în același timp documente care mută același bun."""
import threading
import time
from datetime import date, datetime
from decimal import Decimal

from inventar import create_app
from inventar.domain import documente
from inventar.domain.comun import EroareValidare
from inventar.domain.documente import LinieNoua, salveaza_ciorna, valideaza
from inventar.domain.persoane import creeaza_persoana
from inventar.extensions import db
from inventar.models import Activitate, Bun, Cont, Document, LinieDocument, Locatie
from tests.conftest import OPERATOR


def test_validari_simultane_nu_muta_de_doua_ori_acelasi_bun(tmp_path, monkeypatch):
    app = create_app({"TESTING": True, "SECRET_KEY": "x",
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'c.db').as_posix()}"})
    with app.app_context():
        db.create_all()
        s = db.session
        loc, act = Locatie(cod="L", denumire="L"), Activitate(cod="A", denumire="A")
        s.add_all([loc, act])
        s.commit()
        a, b, c = (creeaza_persoana(s, OPERATOR, n, None, None, None, loc.id, act.id, date(2025, 1, 1))
                   for n in "ABC")
        bun = Bun(nr_inventar="1", categorie="MF", cont=Cont(simbol="213", sintetic="213", categorie="MF"),
                  denumire="X", um="BUC", pret=Decimal("1"), actualizat_la=datetime.now())
        initial = Document(tip="INITIAL", numar="1", data=date(2025, 1, 1), stare="VALIDAT", creat_la=datetime.now())
        s.add_all([bun, initial, LinieDocument(document=initial, bun=bun, persoana_la=a)])
        s.commit()
        catre_b = salveaza_ciorna(s, OPERATOR, "TRANSFER", date(2025, 2, 1), "1", [LinieNoua(bun.id, a.id, b.id)]).id
        catre_c = salveaza_ciorna(s, OPERATOR, "TRANSFER", date(2025, 2, 1), "2", [LinieNoua(bun.id, a.id, c.id)]).id

    original = documente.detinatori_la

    def lent(*args, **kwargs):
        rezultat = original(*args, **kwargs)
        time.sleep(0.3)  # fereastra în care, fără lacăt, celălalt operator ar citi aceeași stare
        return rezultat

    monkeypatch.setattr(documente, "detinatori_la", lent)
    rezultate: dict[int, str] = {}

    def lucreaza(document_id: int) -> None:
        with app.app_context():
            try:
                valideaza(db.session, OPERATOR, document_id)
                rezultate[document_id] = "validat"
            except EroareValidare:
                rezultate[document_id] = "refuzat"

    fire = [threading.Thread(target=lucreaza, args=(i,)) for i in (catre_b, catre_c)]
    for f in fire:
        f.start()
    for f in fire:
        f.join()
    assert sorted(rezultate.values()) == ["refuzat", "validat"]
