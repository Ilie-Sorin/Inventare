"""Trimiterea listelor pe e-mail (§11).

Un mesaj pe titular (persoana fizică), cu PDF-urile MF și OI ale tuturor gestiunilor lui.
Fluxul: previzualizare → confirmare (se creează lotul, un rând pe destinatar, IN_ASTEPTARE)
→ trimitere pe un fir separat, cu starea salvată pe fiecare destinatar → retrimitere doar
la cei cu eroare. Atașamentele se generează la trimitere, din instantaneu.
"""
import json
import secrets
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.domain.generare import Perimetru
from inventar.domain.sabloane import citeste_sablon
from inventar.drepturi import Actor, cere_rol
from inventar.email.smtp import Conexiune, citeste_smtp, construieste_mesaj
from inventar.formatare import data as data_ro
from inventar.models import Inventar, Persoana, TrimitereEmail
from inventar.pdf.comun import nume_fisier
from inventar.pdf.lista import deseneaza_liste
from inventar.tiparire import (
    antet_liste,
    declaratii_din_inventar,
    deseneaza_declaratii,
    inventar_actual,
    linii_filtrate,
    liste_din_inventar,
)


# (tip, prefixul fișierului) — aceleași nume ca la tipărire.
TIPURI_ATASAMENTE = (("liste", "Inventar"), ("inceput", "Declaratii_inceput"), ("sfarsit", "Declaratii_sfarsit"))


@dataclass
class Destinatar:
    titular_id: int
    nume: str
    adresa: str | None
    gestiuni: list[str] = field(default_factory=list)
    locatii: list[str] = field(default_factory=list)
    atasamente: list[dict] = field(default_factory=list)  # persoana_id, gestiune, categorie, tip, fisier


@dataclass
class Previzualizare:
    inventar: Inventar
    destinatari: list[Destinatar]
    fara_adresa: list[Destinatar]
    subiect: str
    corp: str


class _Campuri(dict):
    def __missing__(self, cheie: str) -> str:
        # Un câmp necunoscut rămâne ca atare, în loc să oprească trimiterea.
        return "{" + cheie + "}"


def completeaza(text: str, destinatar: Destinatar, inventar: Inventar) -> str:
    return text.format_map(_Campuri(nume=destinatar.nume, data=data_ro(inventar.data),
                                    locatie=", ".join(destinatar.locatii)))


def previzualizare(session: Session, inventar_id: int, filtru: Perimetru = Perimetru()) -> Previzualizare:
    inventar = inventar_actual(session, inventar_id)
    pe_titular: dict[int, Destinatar] = {}
    for linie in linii_filtrate(session, inventar, filtru):
        d = pe_titular.setdefault(linie.titular_id, Destinatar(linie.titular_id, linie.titular, None))
        if linie.gestiune not in d.gestiuni:
            d.gestiuni.append(linie.gestiune)
        if linie.locatie not in d.locatii:
            d.locatii.append(linie.locatie)
        # Pentru fiecare gestiune × categorie: lista, declarația de început și cea de sfârșit.
        for tip, prefix in TIPURI_ATASAMENTE:
            atasament = {"persoana_id": linie.persoana_id, "gestiune": linie.gestiune, "categorie": linie.categorie,
                         "tip": tip,
                         "fisier": nume_fisier(prefix, inventar.data.isoformat(), linie.gestiune, linie.categorie)}
            if atasament not in d.atasamente:
                d.atasamente.append(atasament)
    adrese = dict(session.execute(select(Persoana.id, Persoana.email).where(Persoana.id.in_(pe_titular))).all())
    ordine_tip = {tip: i for i, (tip, _) in enumerate(TIPURI_ATASAMENTE)}
    for d in pe_titular.values():
        d.adresa = adrese.get(d.titular_id) or None
        d.atasamente.sort(key=lambda a: (a["gestiune"], a["categorie"], ordine_tip[a["tip"]]))
    toti = sorted(pe_titular.values(), key=lambda d: d.nume)
    subiect, corp = citeste_sablon(session, "email_inventar")
    return Previzualizare(inventar, [d for d in toti if d.adresa], [d for d in toti if not d.adresa],
                          subiect or "", corp)


def porneste(session: Session, actor: Actor, inventar_id: int, director_instanta: Path,
             filtru: Perimetru = Perimetru()) -> str:
    """Creează lotul (un rând IN_ASTEPTARE pe destinatar); trimiterea propriu-zisă e `trimite_lot`."""
    cere_rol(actor, "OPERATOR")
    if not citeste_smtp(session, director_instanta, cu_parola=False).configurat:
        raise EroareValidare("Setările SMTP nu sunt completate; administratorul le introduce în Administrare → E-mail.")
    p = previzualizare(session, inventar_id, filtru)
    if not p.destinatari:
        raise EroareValidare("Niciun titular din selecție nu are adresă de e-mail.")
    lot, acum = secrets.token_hex(8), datetime.now()
    for d in p.destinatari:
        session.add(TrimitereEmail(
            lot=lot, inventar_id=p.inventar.id, titular_id=d.titular_id, adresa=d.adresa, stare="IN_ASTEPTARE",
            creat_la=acum, atasamente_json=json.dumps(d.atasamente, ensure_ascii=False),
            subiect=completeaza(p.subiect, d, p.inventar), corp=completeaza(p.corp, d, p.inventar),
        ))
    jurnal.scrie(session, actor, "EMAIL_LOT", "inventar", p.inventar.id, {
        "lot": lot, "filtru": json.loads(filtru.json()), "destinatari": len(p.destinatari),
        "fara_adresa": [d.nume for d in p.fara_adresa],
    })
    session.commit()
    return lot


def _atasamente(session: Session, inventar: Inventar, trimitere: TrimitereEmail,
                director_instanta: Path) -> list[tuple[str, bytes]]:
    antet = antet_liste(session, inventar, director_instanta)
    rezultat = []
    for a in json.loads(trimitere.atasamente_json):
        filtru = Perimetru(persoane=(a["persoana_id"],), categorii=(a["categorie"],))
        tip = a.get("tip", "liste")
        if tip == "liste":
            continut = deseneaza_liste(liste_din_inventar(session, inventar, filtru), antet)
        else:
            continut = deseneaza_declaratii(session, inventar, declaratii_din_inventar(session, inventar, filtru), tip)
        rezultat.append((a["fisier"], continut))
    return rezultat


def trimite_lot(session: Session, actor: Actor, lot: str, director_instanta: Path) -> tuple[int, int]:
    """Trimite rândurile IN_ASTEPTARE ale lotului; fiecare destinatar se salvează separat,
    ca o oprire la mijloc să nu piardă ce s-a trimis deja. Întoarce (trimise, erori)."""
    randuri = list(session.scalars(select(TrimitereEmail).where(
        TrimitereEmail.lot == lot, TrimitereEmail.stare == "IN_ASTEPTARE").order_by(TrimitereEmail.id)))
    if not randuri:
        return 0, 0
    inventar = session.get(Inventar, randuri[0].inventar_id)
    trimise = erori = 0
    eroare_conexiune: str | None = None
    try:
        setari = citeste_smtp(session, director_instanta)
    except EroareValidare as e:  # de ex. parola nu se mai poate decripta
        setari, eroare_conexiune = None, str(e)
    conexiune = Conexiune(setari)
    try:
        for r in randuri:
            if eroare_conexiune is not None:
                r.stare, r.eroare = "EROARE", eroare_conexiune
            else:
                # Orice eroare se salvează pe destinatar și nu oprește lotul.
                try:
                    mesaj = construieste_mesaj(conexiune.setari, r.adresa, r.subiect, r.corp,
                                               _atasamente(session, inventar, r, director_instanta))
                except Exception as e:
                    r.stare, r.eroare = "EROARE", f"Pregătirea mesajului: {type(e).__name__}: {e}"[:1000]
                else:
                    try:
                        conexiune.trimite(mesaj)
                    except Exception as e:
                        r.stare, r.eroare = "EROARE", f"{type(e).__name__}: {e}"[:1000]
                        # Nicio conexiune deschisă: problema e la server, nu la destinatar; restul lotului
                        # primește aceeași eroare, fără să mai aștepte fiecare expirarea conexiunii.
                        if conexiune.smtp is None:
                            eroare_conexiune = r.eroare
                    else:
                        r.stare, r.eroare, r.trimis_la = "TRIMIS", None, datetime.now()
            if r.stare == "TRIMIS":
                trimise += 1
            else:
                erori += 1
            jurnal.scrie(session, actor, "EMAIL_TRIMIS" if r.stare == "TRIMIS" else "EMAIL_EROARE",
                         "trimitere_email", r.id, {"lot": lot, "adresa": r.adresa, "eroare": r.eroare},
                         rezultat="OK" if r.stare == "TRIMIS" else "EROARE")
            session.commit()
    finally:
        conexiune.inchide()
    return trimise, erori


def pregateste_retrimiterea(session: Session, actor: Actor, lot: str, include_intrerupte: bool) -> int:
    """Doar destinatarii cu eroare (și, dacă firul de trimitere nu mai rulează, cei rămași în așteptare)."""
    cere_rol(actor, "OPERATOR")
    stari = ("EROARE", "IN_ASTEPTARE") if include_intrerupte else ("EROARE",)
    randuri = list(session.scalars(select(TrimitereEmail).where(TrimitereEmail.lot == lot,
                                                                TrimitereEmail.stare.in_(stari))))
    if not randuri:
        raise EroareValidare("Nu există destinatari cu eroare în acest lot.")
    inventar_actual(session, randuri[0].inventar_id)
    for r in randuri:
        r.stare, r.eroare = "IN_ASTEPTARE", None
    jurnal.scrie(session, actor, "EMAIL_RETRIMITERE", "inventar", randuri[0].inventar_id,
                 {"lot": lot, "destinatari": len(randuri)})
    session.commit()
    return len(randuri)


def sumar_loturi(session: Session) -> list[dict]:
    rezultat: dict[str, dict] = {}
    for r in session.scalars(select(TrimitereEmail).order_by(TrimitereEmail.id.desc())):
        s = rezultat.setdefault(r.lot, {"lot": r.lot, "inventar_id": r.inventar_id, "creat_la": r.creat_la,
                                        "stari": defaultdict(int)})
        s["stari"][r.stare] += 1
    return list(rezultat.values())


def trimite_test(session: Session, actor: Actor, director_instanta: Path, adresa: str) -> None:
    """Mesaj de probă, trimis imediat, pentru verificarea setărilor SMTP."""
    cere_rol(actor, "ADMIN")
    setari = citeste_smtp(session, director_instanta)
    if not setari.configurat:
        raise EroareValidare("Completați întâi serverul și adresa expeditorului.")
    conexiune = Conexiune(setari)
    try:
        conexiune.trimite(construieste_mesaj(setari, adresa, "Mesaj de probă — liste de inventariere",
                                             "Setările SMTP ale aplicației de inventariere funcționează.", []))
    except Exception as e:
        jurnal.scrie(session, actor, "EMAIL_TEST", detalii={"adresa": adresa, "eroare": str(e)}, rezultat="EROARE")
        session.commit()
        raise EroareValidare(f"Trimiterea a eșuat: {type(e).__name__}: {e}") from None
    finally:
        conexiune.inchide()
    jurnal.scrie(session, actor, "EMAIL_TEST", detalii={"adresa": adresa})
    session.commit()
