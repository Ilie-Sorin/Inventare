"""Inventarul generat: instantaneul situației la data D, din care se tipăresc listele (§7.6).

Generarea copiază în `inventar_linie` tot ce apare pe liste, ca o modificare
ulterioară (document, redenumire, sincronizare) să nu schimbe un inventar deja făcut.
Un document validat sau anulat cu data ≤ D marchează NEACTUALIZAT inventarele
GENERAT; cele BLOCAT (semnate) rămân neatinse.
"""
import json
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session, aliased

from inventar import jurnal
from inventar.domain.comisii import comisie_la
from inventar.domain.comun import EroareValidare, curata_text
from inventar.domain.stoc import nerepartizate, situatia_la
from inventar.drepturi import Actor, cere_rol
from inventar.models import (
    Activitate,
    Bun,
    Cont,
    Document,
    Grup,
    Inventar,
    InventarComisie,
    InventarLinie,
    Locatie,
    Persoana,
    Sincronizare,
    TrimitereEmail,
    grup_persoana,
)


@dataclass(frozen=True)
class Perimetru:
    """Ce intră în inventar. O listă goală înseamnă „toate”; dimensiunile se combină cu ȘI,
    iar persoanele alese direct și cele din grupuri se adună."""

    locatii: tuple[int, ...] = ()
    activitati: tuple[int, ...] = ()
    persoane: tuple[int, ...] = ()
    grupuri: tuple[int, ...] = ()
    categorii: tuple[str, ...] = ()
    conturi: tuple[str, ...] = ()  # conturi sintetice (3 cifre)

    def normalizat(self) -> "Perimetru":
        return Perimetru(**{f.name: tuple(sorted(set(getattr(self, f.name)))) for f in fields(self)})

    def json(self) -> str:
        return json.dumps({k: list(v) for k, v in asdict(self.normalizat()).items()}, sort_keys=True)

    @classmethod
    def din_json(cls, text: str) -> "Perimetru":
        return cls(**{k: tuple(v) for k, v in json.loads(text).items()}).normalizat()

    @property
    def complet(self) -> bool:
        return not any(getattr(self, f.name) for f in fields(self))


def _verifica_perimetru(session: Session, p: Perimetru) -> None:
    for model, valori, nume in ((Locatie, p.locatii, "locații"), (Activitate, p.activitati, "activități"),
                                (Persoana, p.persoane, "persoane"), (Grup, p.grupuri, "grupuri")):
        if valori and session.scalar(select(func.count()).select_from(model).where(model.id.in_(valori))) != len(valori):
            raise EroareValidare(f"Perimetrul conține {nume} inexistente.")
    if set(p.categorii) - {"MF", "OI"}:
        raise EroareValidare("Categoriile pot fi doar MF și OI.")
    if any(len(c) != 3 or not c.isdigit() for c in p.conturi):
        raise EroareValidare("Conturile din perimetru sunt conturi sintetice de 3 cifre.")


def data_ultimei_sincronizari(session: Session) -> date | None:
    """Când au fost încărcate ultima dată datele contabile: importul inițial sau o sincronizare aplicată."""
    momente = [
        session.scalar(select(Document.creat_la).where(Document.tip == "INITIAL")),
        session.scalar(select(func.max(Sincronizare.incarcat_la)).where(Sincronizare.stare == "APLICATA")),
    ]
    momente = [m for m in momente if m]
    return max(momente).date() if momente else None


def avertismente(session: Session, data: date, perimetru: Perimetru) -> list[str]:
    """Verificările de dinainte de generare: nu blochează, dar operatorul trebuie să le vadă."""
    mesaje = []
    sincronizare = data_ultimei_sincronizari(session)
    if sincronizare is None:
        mesaje.append("Datele contabile nu au fost încă importate.")
    elif sincronizare < data:
        mesaje.append(f"Ultima încărcare a exportului contabil este din {sincronizare:%d.%m.%Y}, anterioară datei "
                      "inventarului: bunurile intrate între timp în contabilitate nu apar.")
    libere = [b for b in nerepartizate(session, data)
              if (not perimetru.categorii or b.categorie in perimetru.categorii)
              and (not perimetru.conturi or b.cont.sintetic in perimetru.conturi)
              and not (b.nr_doc_casare or b.data_casare)]
    if libere:
        mesaje.append(f"Există {len(libere)} bunuri nerepartizate la {data:%d.%m.%Y}; ele nu apar pe nicio listă.")
    for locatie_id, denumire in session.execute(
        select(Locatie.id, Locatie.denumire).where(Locatie.id.in_(select(_randuri(data, perimetru).subquery().c.locatie_id)))
    ):
        if comisie_la(session, locatie_id, data) is None:
            mesaje.append(f"Locația {denumire} nu are comisie de inventariere la {data:%d.%m.%Y}.")
    return mesaje


def _randuri(data: date, p: Perimetru):
    """Interogarea care produce liniile instantaneului, cu filtrele perimetrului."""
    stoc = situatia_la(data).subquery()
    titular = aliased(Persoana)
    interogare = (
        select(
            Bun.id.label("bun_id"), Bun.nr_inventar, Bun.nr_inventar_vechi, Bun.denumire, Bun.um, Bun.serie,
            Bun.categorie, Cont.simbol.label("cont"), Cont.sintetic.label("cont_sintetic"), Bun.pret,
            Bun.data_amortizare_integrala,
            Persoana.id.label("persoana_id"), Persoana.nume.label("gestiune"),
            func.coalesce(titular.id, Persoana.id).label("titular_id"),
            func.coalesce(titular.nume, Persoana.nume).label("titular"),
            Locatie.id.label("locatie_id"), Locatie.denumire.label("locatie"),
            Activitate.id.label("activitate_id"), Activitate.denumire.label("activitate"),
        )
        .select_from(stoc)
        .join(Bun, Bun.id == stoc.c.bun_id)
        .join(Cont, Cont.id == Bun.cont_id)
        .join(Persoana, Persoana.id == stoc.c.persoana_id)
        .outerjoin(titular, titular.id == Persoana.titular_id)
        .join(Locatie, Locatie.id == stoc.c.locatie_id)
        .join(Activitate, Activitate.id == stoc.c.activitate_id)
    )
    if p.locatii:
        interogare = interogare.where(Locatie.id.in_(p.locatii))
    if p.activitati:
        interogare = interogare.where(Activitate.id.in_(p.activitati))
    if p.persoane or p.grupuri:
        din_grupuri = select(grup_persoana.c.persoana_id).where(grup_persoana.c.grup_id.in_(p.grupuri))
        interogare = interogare.where(or_(Persoana.id.in_(p.persoane), Persoana.id.in_(din_grupuri)))
    if p.categorii:
        interogare = interogare.where(Bun.categorie.in_(p.categorii))
    if p.conturi:
        interogare = interogare.where(Cont.sintetic.in_(p.conturi))
    return interogare


def _umple(session: Session, inventar: Inventar, perimetru: Perimetru) -> int:
    randuri = [dict(r._mapping, inventar_id=inventar.id) for r in session.execute(_randuri(inventar.data, perimetru))]
    if randuri:
        session.execute(insert(InventarLinie), randuri)
    locatii = {(r["locatie_id"], r["locatie"]) for r in randuri}
    for locatie_id, denumire in sorted(locatii, key=lambda x: x[1]):
        comisie = comisie_la(session, locatie_id, inventar.data)
        membri = [{"nume": m.nume, "calitate": m.calitate} for m in comisie.membri] if comisie else []
        inventar.comisii.append(InventarComisie(locatie_id=locatie_id, locatie=denumire,
                                                membri_json=json.dumps(membri, ensure_ascii=False)))
    inventar.nr_linii = len(randuri)
    return len(randuri)


def genereaza(session: Session, actor: Actor, data: date, perimetru: Perimetru) -> Inventar:
    cere_rol(actor, "OPERATOR")
    perimetru = perimetru.normalizat()
    _verifica_perimetru(session, perimetru)
    existent = session.scalar(select(Inventar.id).where(Inventar.data == data,
                                                        Inventar.perimetru_json == perimetru.json()))
    if existent:
        raise EroareValidare(f"Există deja un inventar la {data:%d.%m.%Y} cu același perimetru (nr. {existent}).")
    try:
        inventar = Inventar(data=data, perimetru_json=perimetru.json(), stare="GENERAT",
                            generat_de=actor.utilizator_id, generat_la=datetime.now(), nr_linii=0)
        session.add(inventar)
        session.flush()
        _umple(session, inventar, perimetru)
        jurnal.scrie(session, actor, "INVENTAR_GENERAT", "inventar", inventar.id,
                     {"data": data, "perimetru": json.loads(perimetru.json()), "linii": inventar.nr_linii})
        session.commit()
    except Exception:
        session.rollback()
        raise
    return inventar


def _inventar(session: Session, inventar_id: int) -> Inventar:
    inventar = session.get(Inventar, inventar_id)
    if inventar is None:
        raise EroareValidare("Inventarul nu există.")
    return inventar


def _goleste(session: Session, inventar: Inventar) -> None:
    session.execute(delete(InventarLinie).where(InventarLinie.inventar_id == inventar.id))
    inventar.comisii.clear()
    session.flush()


def regenereaza(session: Session, actor: Actor, inventar_id: int) -> Inventar:
    """Ștergere + generare cu aceiași parametri, în aceeași tranzacție; inventarul își păstrează numărul."""
    cere_rol(actor, "OPERATOR")
    inventar = _inventar(session, inventar_id)
    if inventar.stare == "BLOCAT":
        raise EroareValidare("Inventarul este blocat (semnat); cereți deblocarea administratorului.")
    try:
        inainte = inventar.nr_linii
        _goleste(session, inventar)
        _umple(session, inventar, Perimetru.din_json(inventar.perimetru_json))
        inventar.stare, inventar.generat_la, inventar.generat_de = "GENERAT", datetime.now(), actor.utilizator_id
        jurnal.scrie(session, actor, "INVENTAR_REGENERAT", "inventar", inventar.id,
                     {"data": inventar.data, "linii_inainte": inainte, "linii_dupa": inventar.nr_linii})
        session.commit()
    except Exception:
        session.rollback()
        raise
    return inventar


def blocheaza(session: Session, actor: Actor, inventar_id: int) -> Inventar:
    cere_rol(actor, "OPERATOR")
    inventar = _inventar(session, inventar_id)
    if inventar.stare != "GENERAT":
        raise EroareValidare("Se poate bloca doar un inventar în starea GENERAT (actualizat).")
    inventar.stare = "BLOCAT"
    jurnal.scrie(session, actor, "INVENTAR_BLOCAT", "inventar", inventar.id, {"data": inventar.data})
    session.commit()
    return inventar


def deblocheaza(session: Session, actor: Actor, inventar_id: int, motiv: str) -> Inventar:
    cere_rol(actor, "ADMIN")
    motiv = curata_text(motiv)
    if not motiv:
        raise EroareValidare("Motivul deblocării este obligatoriu.")
    inventar = _inventar(session, inventar_id)
    if inventar.stare != "BLOCAT":
        raise EroareValidare("Inventarul nu este blocat.")
    # Cât a fost blocat, documentele nu l-au mai marcat; după deblocare trebuie revăzut.
    inventar.stare, inventar.motiv_deblocare = "NEACTUALIZAT", motiv
    jurnal.scrie(session, actor, "INVENTAR_DEBLOCAT", "inventar", inventar.id, {"data": inventar.data, "motiv": motiv})
    session.commit()
    return inventar


def sterge(session: Session, actor: Actor, inventar_id: int) -> None:
    cere_rol(actor, "OPERATOR")
    inventar = _inventar(session, inventar_id)
    if inventar.stare == "BLOCAT":
        raise EroareValidare("Inventarul este blocat (semnat); cereți deblocarea administratorului.")
    detalii = {"data": inventar.data, "perimetru": json.loads(inventar.perimetru_json), "linii": inventar.nr_linii}
    # Trimiterile de e-mail trimit către inventar (cheie străină); fără ele ștergerea ar eșua. Urma lor
    # rămâne în jurnal (EMAIL_TRIMIS etc.) și în numărul din această înregistrare.
    trimiteri = session.execute(delete(TrimitereEmail).where(TrimitereEmail.inventar_id == inventar_id))
    detalii["trimiteri_email"] = trimiteri.rowcount
    _goleste(session, inventar)
    session.delete(inventar)
    jurnal.scrie(session, actor, "INVENTAR_STERS", "inventar", inventar_id, detalii)
    session.commit()

