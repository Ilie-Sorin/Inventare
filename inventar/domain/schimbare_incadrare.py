"""Asistentul de schimbare a încadrării (document INCADRARE, §7.4).

Persoana trece în altă locație / activitate de la data D. Pentru fiecare bun al ei,
operatorul alege: îl urmează (nu se schimbă nimic la bun) sau se predă unei alte
persoane din vechea locație. Predările devin documente TRANSFER validate, cu
aceeași dată. Totul se face într-o singură tranzacție.
"""
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare, text_optional
from inventar.domain.documente import (
    data_initiala,
    rezerva_scrierea,
    urmatorul_numar,
    valideaza_fara_commit,
)
from inventar.domain.incadrare import creeaza_incadrare, incadrare_la, incadrari_la
from inventar.domain.neactualizare import marcheaza_neactualizate
from inventar.domain.stoc import bunuri_la_persoana
from inventar.drepturi import Actor, cere_rol
from inventar.models import Document, Incadrare, LinieDocument, Persoana


def destinatari_predare(session: Session, persoana_id: int, data: date) -> list[Persoana]:
    """Persoanele active din locația pe care persoana o are la data D (înainte de schimbare)."""
    actuala = incadrare_la(session, persoana_id, data)
    if actuala is None:
        return []
    curente = incadrari_la(data).subquery()
    return list(session.scalars(
        select(Persoana).join(curente, curente.c.persoana_id == Persoana.id)
        .where(curente.c.locatie_id == actuala.locatie_id, Persoana.activ.is_(True), Persoana.id != persoana_id)
        .order_by(Persoana.nume)
    ))


def schimba_incadrarea(
    session: Session, actor: Actor, persoana_id: int, locatie_id: int, activitate_id: int, valabil_de_la: date,
    motiv: str | None, predari: dict[int, int] | None = None,
) -> Incadrare:
    """`predari` = {bun_id: persoana care îl primește}; bunurile nemenționate urmează persoana."""
    cere_rol(actor, "OPERATOR")
    predari = predari or {}
    rezerva_scrierea(session)
    try:
        persoana = session.get(Persoana, persoana_id)
        if persoana is None or not persoana.activ:
            raise EroareValidare("Persoana nu există sau este inactivă.")
        initiala = data_initiala(session)
        if initiala and valabil_de_la < initiala:
            raise EroareValidare(f"Data nu poate fi înaintea inventarului inițial ({initiala:%d.%m.%Y}).")
        bunuri_proprii = {b.id for b in bunuri_la_persoana(session, persoana_id, valabil_de_la)}
        straine = set(predari) - bunuri_proprii
        if straine:
            raise EroareValidare(f"{len(straine)} bunuri alese pentru predare nu se află la „{persoana.nume}” "
                                 f"la {valabil_de_la:%d.%m.%Y}.")
        permisi = {p.id for p in destinatari_predare(session, persoana_id, valabil_de_la)}
        if set(predari.values()) - permisi:
            raise EroareValidare("Bunurile se pot preda doar persoanelor active din vechea locație.")

        acum = datetime.now()
        document = Document(
            tip="INCADRARE", numar=urmatorul_numar(session, "INCADRARE", valabil_de_la.year), data=valabil_de_la,
            explicatie=text_optional(motiv), stare="VALIDAT", creat_de=actor.utilizator_id, creat_la=acum,
            validat_de=actor.utilizator_id, validat_la=acum,
        )
        session.add(document)
        session.flush()
        incadrare = creeaza_incadrare(session, persoana_id, locatie_id, activitate_id, valabil_de_la, motiv,
                                      document_id=document.id)
        marcheaza_neactualizate(session, actor, valabil_de_la, f"schimbare încadrare nr. {document.numar}")

        pe_destinatar: dict[int, list[int]] = defaultdict(list)
        for bun_id, destinatar in predari.items():
            pe_destinatar[destinatar].append(bun_id)
        transferuri = []
        for destinatar, bun_ids in sorted(pe_destinatar.items()):
            transfer = Document(
                tip="TRANSFER", numar=urmatorul_numar(session, "TRANSFER", valabil_de_la.year), data=valabil_de_la,
                explicatie=f"Predare la schimbarea încadrării (document INCADRARE nr. {document.numar})",
                stare="CIORNA", creat_de=actor.utilizator_id, creat_la=acum,
            )
            session.add(transfer)
            session.flush()
            for bun_id in sorted(bun_ids):
                session.add(LinieDocument(document_id=transfer.id, bun_id=bun_id,
                                          persoana_de_la_id=persoana_id, persoana_la_id=destinatar))
            session.flush()
            session.refresh(transfer)
            valideaza_fara_commit(session, actor, transfer)
            transferuri.append(transfer.id)

        jurnal.scrie(session, actor, "INCADRARE_SCHIMBATA", "document", document.id, {
            "persoana_id": persoana_id, "locatie_id": locatie_id, "activitate_id": activitate_id,
            "valabil_de_la": valabil_de_la, "motiv": text_optional(motiv),
            "bunuri_care_urmeaza": len(bunuri_proprii) - len(predari), "transferuri": transferuri,
        })
        session.commit()
    except Exception:
        session.rollback()
        raise
    return incadrare
