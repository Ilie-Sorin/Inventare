"""Locații, activități și grupuri de persoane."""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare, aplica_modificari, curata_text, exista_alta_valoare
from inventar.domain.incadrare import incadrari_la
from inventar.drepturi import Actor, cere_rol
from inventar.models import Activitate, Grup, Locatie, Persoana

# Locațiile și activitățile au aceeași formă, dar rămân nomenclatoare
# independente (§7.2): aceeași denumire poate exista în ambele.
Nomenclator = type[Locatie] | type[Activitate]
_NUME = {Locatie: "locatie", Activitate: "activitate"}


def _verifica_cod_unic(session: Session, model: Nomenclator, cod: str, exclude_id: int | None = None) -> None:
    if exista_alta_valoare(session, model.cod, cod, exclude_id):
        raise EroareValidare(f"Codul „{cod}” există deja.")


def _date_curate(cod: str, denumire: str) -> tuple[str, str]:
    cod, denumire = curata_text(cod), curata_text(denumire)
    if not cod:
        raise EroareValidare("Codul este obligatoriu.")
    if not denumire:
        raise EroareValidare("Denumirea este obligatorie.")
    return cod, denumire


def creeaza_nomenclator(session: Session, actor: Actor, model: Nomenclator, cod: str, denumire: str):
    cere_rol(actor, "OPERATOR")
    cod, denumire = _date_curate(cod, denumire)
    _verifica_cod_unic(session, model, cod)
    obiect = model(cod=cod, denumire=denumire, activ=True)
    session.add(obiect)
    session.flush()
    nume = _NUME[model]
    jurnal.scrie(session, actor, f"{nume.upper()}_CREATA", nume, obiect.id, {"cod": cod, "denumire": denumire})
    session.commit()
    return obiect


def modifica_nomenclator(session: Session, actor: Actor, model: Nomenclator, obiect_id: int, cod: str,
                         denumire: str):
    cere_rol(actor, "OPERATOR")
    obiect = session.get(model, obiect_id)
    if obiect is None:
        raise EroareValidare("Înregistrarea nu există.")
    cod, denumire = _date_curate(cod, denumire)
    _verifica_cod_unic(session, model, cod, exclude_id=obiect_id)
    schimbari = aplica_modificari(obiect, {"cod": cod, "denumire": denumire})
    if schimbari:
        nume = _NUME[model]
        jurnal.scrie(session, actor, f"{nume.upper()}_MODIFICATA", nume, obiect.id, schimbari)
    session.commit()
    return obiect


def seteaza_activ_nomenclator(session: Session, actor: Actor, model: Nomenclator, obiect_id: int, activ: bool,
                              azi: date | None = None):
    cere_rol(actor, "OPERATOR")
    obiect = session.get(model, obiect_id)
    if obiect is None:
        raise EroareValidare("Înregistrarea nu există.")
    if obiect.activ == activ:
        return obiect
    if not activ:
        # Nu se dezactivează ceva unde sunt încadrate acum persoane active:
        # altfel acestea ar rămâne într-o locație / activitate „inexistentă”.
        curente = incadrari_la(azi or date.today()).subquery()
        coloana = curente.c.locatie_id if model is Locatie else curente.c.activitate_id
        numar = session.scalar(
            select(func.count())
            .select_from(curente)
            .join(Persoana, Persoana.id == curente.c.persoana_id)
            .where(coloana == obiect_id, Persoana.activ.is_(True))
        )
        if numar:
            raise EroareValidare(f"Nu se poate dezactiva: {numar} persoane active sunt încadrate aici.")
    obiect.activ = activ
    nume = _NUME[model]
    jurnal.scrie(session, actor, f"{nume.upper()}_{'ACTIVATA' if activ else 'DEZACTIVATA'}", nume, obiect.id)
    session.commit()
    return obiect


def _verifica_grup(session: Session, denumire: str, persoane_ids: list[int], exclude_id: int | None) -> list[Persoana]:
    if not denumire:
        raise EroareValidare("Denumirea grupului este obligatorie.")
    if exista_alta_valoare(session, Grup.denumire, denumire, exclude_id):
        raise EroareValidare(f"Grupul „{denumire}” există deja.")
    persoane = list(session.scalars(select(Persoana).where(Persoana.id.in_(set(persoane_ids)))))
    if len(persoane) != len(set(persoane_ids)):
        raise EroareValidare("Unele persoane alese nu există.")
    return persoane


def creeaza_grup(session: Session, actor: Actor, denumire: str, persoane_ids: list[int]) -> Grup:
    cere_rol(actor, "OPERATOR")
    denumire = curata_text(denumire)
    persoane = _verifica_grup(session, denumire, persoane_ids, None)
    grup = Grup(denumire=denumire, persoane=persoane)
    session.add(grup)
    session.flush()
    jurnal.scrie(session, actor, "GRUP_CREAT", "grup", grup.id,
                 {"denumire": denumire, "persoane": sorted(p.id for p in persoane)})
    session.commit()
    return grup


def modifica_grup(session: Session, actor: Actor, grup_id: int, denumire: str, persoane_ids: list[int]) -> Grup:
    cere_rol(actor, "OPERATOR")
    grup = session.get(Grup, grup_id)
    if grup is None:
        raise EroareValidare("Grupul nu există.")
    denumire = curata_text(denumire)
    persoane = _verifica_grup(session, denumire, persoane_ids, grup_id)
    vechi = {p.id for p in grup.persoane}
    noi = {p.id for p in persoane}
    detalii: dict = aplica_modificari(grup, {"denumire": denumire})
    if vechi != noi:
        grup.persoane = persoane
        detalii["adaugate"] = sorted(noi - vechi)
        detalii["scoase"] = sorted(vechi - noi)
    if detalii:
        jurnal.scrie(session, actor, "GRUP_MODIFICAT", "grup", grup.id, detalii)
    session.commit()
    return grup


def sterge_grup(session: Session, actor: Actor, grup_id: int) -> None:
    """Grupul e doar un filtru de listare, nu apare în documente, deci se poate șterge."""
    cere_rol(actor, "OPERATOR")
    grup = session.get(Grup, grup_id)
    if grup is None:
        raise EroareValidare("Grupul nu există.")
    detalii = {"denumire": grup.denumire, "persoane": sorted(p.id for p in grup.persoane)}
    session.delete(grup)
    jurnal.scrie(session, actor, "GRUP_STERS", "grup", grup_id, detalii)
    session.commit()
