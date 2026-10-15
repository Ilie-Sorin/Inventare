"""Tipărirea unui document de mișcare validat (bon de mișcare)."""
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.domain.documente import MOTIVE_IESIRE
from inventar.domain.incadrare import incadrare_la
from inventar.domain.setari import citeste_setari
from inventar.drepturi import Actor, cere_rol
from inventar.models import Document, Persoana, Utilizator
from inventar.pdf.comun import nume_fisier
from inventar.pdf.document_miscare import TITLURI, DocumentMiscare, Parte, RandDocument, deseneaza_document
from inventar.formatare import data as data_ro


def _parte(session: Session, persoana: Persoana, document: Document) -> Parte:
    """Locația și activitatea sunt cele de la data documentului, nu cele de azi."""
    incadrare = incadrare_la(session, persoana.id, document.data)
    return Parte(persoana.nume, persoana.nume_semnatura,
                 incadrare.locatie.denumire if incadrare else "—",
                 incadrare.activitate.denumire if incadrare else "—")


def _distincte(persoane: list[Persoana | None]) -> list[Persoana]:
    return list({p.id: p for p in persoane if p is not None}.values())


def tipareste_document(session: Session, actor: Actor, document_id: int) -> tuple[str, bytes]:
    cere_rol(actor, "CONSULTARE")
    document = session.get(Document, document_id)
    if document is None:
        raise EroareValidare("Documentul nu există.")
    if document.tip not in TITLURI:
        raise EroareValidare("Pentru acest tip de document nu se tipărește bon de mișcare.")
    if document.stare != "VALIDAT":
        raise EroareValidare("Se tipărește numai un document validat.")

    setari = citeste_setari(session)
    de_la = _distincte([linie.persoana_de_la for linie in document.linii])
    la = _distincte([linie.persoana_la for linie in document.linii])
    randuri = []
    for linie in document.linii:
        b = linie.bun
        casare = None
        if document.tip == "IESIRE" and (b.nr_doc_casare or b.data_casare):
            casare = " / ".join(x for x in (f"nr. {b.nr_doc_casare}" if b.nr_doc_casare else "",
                                            data_ro(b.data_casare) if b.data_casare else "") if x)
        randuri.append(RandDocument(b.nr_inventar, b.nr_inventar_vechi, b.denumire, b.serie, b.um, b.categorie,
                                    b.cont.simbol, b.pret, casare))
    creator = session.get(Utilizator, document.creat_de) if document.creat_de else None
    continut = deseneaza_document(DocumentMiscare(
        document.tip, document.serie, document.numar, document.data, setari["unitate"], setari["unitate_superioara"],
        document.explicatie, MOTIVE_IESIRE.get(document.motiv_iesire or "", document.motiv_iesire),
        [_parte(session, p, document) for p in de_la], [_parte(session, p, document) for p in la], randuri,
        creator.username if creator else "",
    ))
    nume = nume_fisier("Bon_miscare", document.tip, document.data.isoformat(), document.serie or "", document.numar)
    jurnal.scrie(session, actor, "PDF_DOCUMENT", "document", document.id, {"fisier": nume, "linii": len(randuri)})
    session.commit()
    return nume, continut
