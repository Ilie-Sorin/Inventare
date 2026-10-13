"""Documente: ciornă, validare, anulare și regulile cronologice (§7.4).

Regula cronologică folosește aceeași ordine ca stocul, (data, document.id): un
document nu se validează (și nu se anulează) dacă vreunul dintre bunurile lui are
o mișcare validată care vine după el în această ordine. Astfel lanțul fiecărui
bun rămâne consistent, inclusiv pentru documente din aceeași zi.
"""
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare, curata_text, text_optional
from inventar.domain.incadrare import incadrare_la
from inventar.domain.neactualizare import marcheaza_neactualizate
from inventar.domain.stoc import detinatori_la
from inventar.drepturi import Actor, cere_rol
from inventar.models import Bun, Document, Incadrare, LinieDocument, Persoana

TIPURI_MANUALE = ("INTRARE", "IESIRE", "TRANSFER")
MOTIVE_IESIRE = {
    "CASARE": "Casare",
    "VANZARE": "Vânzare",
    "TRANSFER_UNITATE": "Transfer la altă unitate",
    "MINUS_INVENTAR": "Minus la inventar",
}
MAX_ERORI_AFISATE = 25


@dataclass(frozen=True)
class LinieNoua:
    bun_id: int
    persoana_de_la_id: int | None
    persoana_la_id: int | None


def rezerva_scrierea(session: Session) -> None:
    """Ia lacătul de scriere SQLite înainte de verificări.

    Mai mulți operatori pot valida simultan; fără lacăt, doi ar putea verifica
    aceeași stare și ar muta amândoi același bun. O instrucțiune de scriere fără
    efect pornește tranzacția de scriere, iar ceilalți așteaptă (busy_timeout).
    """
    session.execute(text("UPDATE document SET id = id WHERE 0"))


def data_initiala(session: Session) -> date | None:
    return session.scalar(select(Document.data).where(Document.tip == "INITIAL", Document.stare == "VALIDAT"))


def urmatorul_numar(session: Session, tip: str, an: int) -> str:
    numere = session.scalars(select(Document.numar).where(
        Document.tip == tip, Document.data >= date(an, 1, 1), Document.data <= date(an, 12, 31)))
    maxim = max((int(n) for n in numere if n.isdigit()), default=0)
    return str(maxim + 1)


def _verifica_data(session: Session, data: date) -> None:
    initiala = data_initiala(session)
    if initiala and data < initiala:
        raise EroareValidare(f"Data documentului nu poate fi înaintea inventarului inițial ({initiala:%d.%m.%Y}).")


def _verifica_forma(tip: str, numar: str, motiv_iesire: str | None, linii: list[LinieNoua]) -> None:
    if tip not in TIPURI_MANUALE:
        raise EroareValidare(f"Tip de document nepermis aici: {tip}.")
    if not numar:
        raise EroareValidare("Numărul documentului este obligatoriu.")
    if tip == "IESIRE" and motiv_iesire not in MOTIVE_IESIRE:
        raise EroareValidare("Motivul ieșirii este obligatoriu.")
    if not linii:
        raise EroareValidare("Documentul trebuie să conțină cel puțin un bun.")
    if len({linie.bun_id for linie in linii}) != len(linii):
        raise EroareValidare("Un bun apare de mai multe ori în document.")
    for linie in linii:
        if tip == "INTRARE" and (linie.persoana_de_la_id or not linie.persoana_la_id):
            raise EroareValidare("O intrare nu are predător și trebuie să aibă un destinatar.")
        if tip == "IESIRE" and (linie.persoana_la_id or not linie.persoana_de_la_id):
            raise EroareValidare("O ieșire nu are destinatar și trebuie să aibă persoana care predă.")
        if tip == "TRANSFER":
            if not linie.persoana_de_la_id or not linie.persoana_la_id:
                raise EroareValidare("Un transfer are persoana care predă și persoana care primește.")
            if linie.persoana_de_la_id == linie.persoana_la_id:
                raise EroareValidare("Un transfer nu poate fi către aceeași persoană.")


def salveaza_ciorna(
    session: Session, actor: Actor, tip: str, data: date, numar: str, linii: list[LinieNoua], *,
    document_id: int | None = None, serie: str | None = None, explicatie: str | None = None,
    motiv_iesire: str | None = None,
) -> Document:
    """Creează sau înlocuiește complet o ciornă. Verificările de stoc se fac la validare."""
    cere_rol(actor, "OPERATOR")
    numar = curata_text(numar)
    _verifica_forma(tip, numar, motiv_iesire, linii)
    _verifica_data(session, data)
    if session.scalar(select(func.count()).select_from(Bun).where(Bun.id.in_([x.bun_id for x in linii]))) != len(linii):
        raise EroareValidare("Unele bunuri alese nu există.")
    acum = datetime.now()
    if document_id is None:
        document = Document(tip=tip, stare="CIORNA", creat_de=actor.utilizator_id, creat_la=acum)
        session.add(document)
        actiune = "DOCUMENT_CREAT"
    else:
        document = session.get(Document, document_id)
        if document is None:
            raise EroareValidare("Documentul nu există.")
        if document.stare != "CIORNA" or document.tip != tip:
            raise EroareValidare("Doar ciornele se pot modifica, fără schimbarea tipului.")
        session.execute(delete(LinieDocument).where(LinieDocument.document_id == document.id))
        session.expire(document, ["linii"])
        actiune = "DOCUMENT_MODIFICAT"
    document.data, document.numar, document.serie = data, numar, text_optional(serie)
    document.explicatie = text_optional(explicatie)
    document.motiv_iesire = motiv_iesire if tip == "IESIRE" else None
    session.flush()
    for linie in linii:
        session.add(LinieDocument(document_id=document.id, bun_id=linie.bun_id,
                                  persoana_de_la_id=linie.persoana_de_la_id, persoana_la_id=linie.persoana_la_id))
    session.flush()
    jurnal.scrie(session, actor, actiune, "document", document.id, {
        "tip": tip, "numar": numar, "data": data, "bunuri": len(linii), "motiv_iesire": document.motiv_iesire,
    })
    session.commit()
    return document


def _miscari_ulterioare(session: Session, document: Document, bun_ids: list[int]) -> set[int]:
    return set(session.scalars(
        select(LinieDocument.bun_id).join(Document, Document.id == LinieDocument.document_id).where(
            Document.stare == "VALIDAT",
            Document.id != document.id,
            LinieDocument.bun_id.in_(bun_ids),
            or_(Document.data > document.data, and_(Document.data == document.data, Document.id > document.id)),
        )
    ))


def _erori_validare(session: Session, document: Document) -> list[str]:
    erori: list[str] = []
    linii = list(document.linii)
    bun_ids = [linie.bun_id for linie in linii]
    ulterioare = _miscari_ulterioare(session, document, bun_ids)
    detinatori = detinatori_la(session, document.data, bun_ids)
    nume = {p.id: p for p in session.scalars(select(Persoana).where(Persoana.id.in_(
        {x.persoana_de_la_id for x in linii} | {x.persoana_la_id for x in linii})))}

    for linie in linii:
        nr = linie.bun.nr_inventar
        if linie.bun_id in ulterioare:
            erori.append(f"Bunul {nr} are o mișcare validată ulterioară acestui document.")
            continue
        repartizat = linie.bun_id in detinatori
        detinator = detinatori.get(linie.bun_id)
        if repartizat and detinator is None:
            erori.append(f"Bunul {nr} a ieșit din evidență și nu mai poate fi mișcat.")
        elif document.tip == "INTRARE" and repartizat:
            erori.append(f"Bunul {nr} este deja repartizat.")
        elif document.tip != "INTRARE" and detinator != linie.persoana_de_la_id:
            erori.append(f"Bunul {nr} nu se află la „{nume[linie.persoana_de_la_id].nume}” la data documentului.")

    for persoana_id in {x.persoana_la_id for x in linii if x.persoana_la_id}:
        persoana = nume[persoana_id]
        if not persoana.activ:
            erori.append(f"Persoana „{persoana.nume}” este inactivă.")
        elif incadrare_la(session, persoana_id, document.data) is None:
            erori.append(f"Persoana „{persoana.nume}” nu are încadrare la {document.data:%d.%m.%Y}.")
    return erori


def valideaza_fara_commit(session: Session, actor: Actor, document: Document) -> None:
    """Folosită și de asistentul de încadrare, care validează mai multe documente într-o tranzacție."""
    if document.stare != "CIORNA":
        raise EroareValidare("Doar ciornele se pot valida.")
    _verifica_data(session, document.data)
    erori = _erori_validare(session, document)
    if erori:
        rest = f" (și încă {len(erori) - MAX_ERORI_AFISATE})" if len(erori) > MAX_ERORI_AFISATE else ""
        raise EroareValidare(" ".join(erori[:MAX_ERORI_AFISATE]) + rest)
    document.stare, document.validat_de, document.validat_la = "VALIDAT", actor.utilizator_id, datetime.now()
    marcheaza_neactualizate(session, actor, document.data, f"validare {document.tip} nr. {document.numar}")
    jurnal.scrie(session, actor, "DOCUMENT_VALIDAT", "document", document.id,
                 {"tip": document.tip, "numar": document.numar, "data": document.data, "bunuri": len(document.linii)})


def valideaza(session: Session, actor: Actor, document_id: int) -> Document:
    cere_rol(actor, "OPERATOR")
    rezerva_scrierea(session)
    document = session.get(Document, document_id)
    if document is None:
        raise EroareValidare("Documentul nu există.")
    try:
        valideaza_fara_commit(session, actor, document)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return document


def _anuleaza_incadrare(session: Session, document: Document) -> dict:
    incadrare = session.scalar(select(Incadrare).where(Incadrare.document_id == document.id))
    if incadrare is None:
        return {}
    ulterioara = session.scalar(select(Incadrare.id).where(
        Incadrare.persoana_id == incadrare.persoana_id, Incadrare.valabil_de_la > incadrare.valabil_de_la))
    if ulterioara:
        raise EroareValidare("Persoana are o încadrare ulterioară; anulați întâi documentul aceleia.")
    detalii = {"incadrare_stearsa": {
        "persoana_id": incadrare.persoana_id, "locatie_id": incadrare.locatie_id,
        "activitate_id": incadrare.activitate_id, "valabil_de_la": incadrare.valabil_de_la,
    }}
    # Încadrarea există doar prin acest document; anulat documentul, ea nu mai are temei.
    session.delete(incadrare)
    return detalii


def anuleaza(session: Session, actor: Actor, document_id: int, motiv: str) -> Document:
    cere_rol(actor, "OPERATOR")
    motiv = curata_text(motiv)
    if not motiv:
        raise EroareValidare("Motivul anulării este obligatoriu.")
    rezerva_scrierea(session)
    document = session.get(Document, document_id)
    if document is None:
        raise EroareValidare("Documentul nu există.")
    if document.tip == "INITIAL":
        raise EroareValidare("Documentul inițial nu se anulează.")
    if document.stare == "ANULAT":
        raise EroareValidare("Documentul este deja anulat.")
    try:
        detalii: dict = {"tip": document.tip, "numar": document.numar, "stare_anterioara": document.stare,
                         "motiv": motiv}
        if document.stare == "VALIDAT":
            ulterioare = _miscari_ulterioare(session, document, [x.bun_id for x in document.linii])
            if ulterioare:
                numere = sorted(session.scalars(select(Bun.nr_inventar).where(Bun.id.in_(ulterioare))))
                raise EroareValidare(f"Nu se poate anula: bunurile {', '.join(numere)} au mișcări validate ulterioare.")
            if document.tip == "INCADRARE":
                detalii |= _anuleaza_incadrare(session, document)
            marcheaza_neactualizate(session, actor, document.data, f"anulare {document.tip} nr. {document.numar}")
        document.stare, document.anulat_de, document.anulat_la = "ANULAT", actor.utilizator_id, datetime.now()
        document.motiv_anulare = motiv
        jurnal.scrie(session, actor, "DOCUMENT_ANULAT", "document", document.id, detalii)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return document
