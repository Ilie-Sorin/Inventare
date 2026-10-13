"""Servicii pentru conturile de utilizator: autentificare, creare, drepturi, parole."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.drepturi import Actor, cere_rol
from inventar.models import ROLURI, Persoana, Utilizator

LUNGIME_MINIMA_PAROLA = 8

# Hash calculat o singură dată, folosit când utilizatorul nu există, ca timpul
# de răspuns să nu dezvăluie ce nume de utilizator sunt valide.
_HASH_FALS = generate_password_hash("parola-inexistenta")


class EroareUtilizator(EroareValidare):
    pass


def actor_pentru(utilizator: Utilizator, ip: str | None) -> Actor:
    return Actor(utilizator_id=utilizator.id, username=utilizator.username, rol=utilizator.rol, ip=ip)


def autentifica(session: Session, username: str, parola: str, ip: str | None) -> Utilizator | None:
    username = username.strip()
    utilizator = session.scalar(select(Utilizator).where(Utilizator.username == username))
    parola_ok = check_password_hash(utilizator.parola_hash if utilizator else _HASH_FALS, parola)
    if utilizator and parola_ok and utilizator.activ:
        jurnal.scrie(session, actor_pentru(utilizator, ip), "AUTENTIFICARE")
        session.commit()
        return utilizator
    motiv = "cont inactiv" if utilizator and parola_ok else "date greșite"
    actor = Actor(utilizator_id=utilizator.id if utilizator else None, username=username[:64], rol="", ip=ip)
    jurnal.scrie(session, actor, "AUTENTIFICARE", detalii={"motiv": motiv}, rezultat="ESEC")
    session.commit()
    return None


def deconecteaza(session: Session, actor: Actor) -> None:
    jurnal.scrie(session, actor, "DECONECTARE")
    session.commit()


def creeaza_utilizator(session: Session, actor: Actor, username: str, parola: str, rol: str) -> Utilizator:
    cere_rol(actor, "ADMIN")
    username = username.strip()
    if not username:
        raise EroareUtilizator("Numele de utilizator este obligatoriu.")
    if rol not in ROLURI:
        raise EroareUtilizator(f"Rol necunoscut: {rol}.")
    if len(parola) < LUNGIME_MINIMA_PAROLA:
        raise EroareUtilizator(f"Parola trebuie să aibă cel puțin {LUNGIME_MINIMA_PAROLA} caractere.")
    if session.scalar(select(Utilizator.id).where(Utilizator.username == username)):
        raise EroareUtilizator(f"Utilizatorul „{username}” există deja.")
    utilizator = Utilizator(username=username, parola_hash=generate_password_hash(parola), rol=rol, activ=True)
    session.add(utilizator)
    session.flush()
    jurnal.scrie(session, actor, "UTILIZATOR_CREAT", "utilizator", utilizator.id, {"username": username, "rol": rol})
    session.commit()
    return utilizator


def _verifica_parola(parola: str) -> None:
    if len(parola) < LUNGIME_MINIMA_PAROLA:
        raise EroareUtilizator(f"Parola trebuie să aibă cel puțin {LUNGIME_MINIMA_PAROLA} caractere.")


def _admini_activi_ramasi(session: Session, exclude_id: int) -> int:
    return len(list(session.scalars(
        select(Utilizator.id).where(Utilizator.rol == "ADMIN", Utilizator.activ.is_(True), Utilizator.id != exclude_id)
    )))


def modifica_utilizator(session: Session, actor: Actor, utilizator_id: int, rol: str, activ: bool,
                        persoana_id: int | None) -> Utilizator:
    cere_rol(actor, "ADMIN")
    utilizator = session.get(Utilizator, utilizator_id)
    if utilizator is None:
        raise EroareUtilizator("Utilizatorul nu există.")
    if rol not in ROLURI:
        raise EroareUtilizator(f"Rol necunoscut: {rol}.")
    if persoana_id is not None and session.get(Persoana, persoana_id) is None:
        raise EroareUtilizator("Persoana aleasă nu există.")
    # Aplicația nu trebuie să rămână fără niciun administrator activ.
    pierde_admin = utilizator.rol == "ADMIN" and utilizator.activ and (rol != "ADMIN" or not activ)
    if pierde_admin and _admini_activi_ramasi(session, utilizator.id) == 0:
        raise EroareUtilizator("Trebuie să rămână cel puțin un administrator activ.")
    schimbari = {}
    for camp, nou in {"rol": rol, "activ": activ, "persoana_id": persoana_id}.items():
        vechi = getattr(utilizator, camp)
        if vechi != nou:
            schimbari[camp] = [vechi, nou]
            setattr(utilizator, camp, nou)
    if schimbari:
        jurnal.scrie(session, actor, "UTILIZATOR_MODIFICAT", "utilizator", utilizator.id,
                     {"username": utilizator.username, **schimbari})
    session.commit()
    return utilizator


def reseteaza_parola(session: Session, actor: Actor, utilizator_id: int, parola_noua: str) -> None:
    cere_rol(actor, "ADMIN")
    utilizator = session.get(Utilizator, utilizator_id)
    if utilizator is None:
        raise EroareUtilizator("Utilizatorul nu există.")
    _verifica_parola(parola_noua)
    utilizator.parola_hash = generate_password_hash(parola_noua)
    jurnal.scrie(session, actor, "PAROLA_RESETATA", "utilizator", utilizator.id, {"username": utilizator.username})
    session.commit()


def schimba_parola_proprie(session: Session, actor: Actor, parola_veche: str, parola_noua: str) -> None:
    utilizator = session.get(Utilizator, actor.utilizator_id)
    if utilizator is None or not check_password_hash(utilizator.parola_hash, parola_veche):
        raise EroareUtilizator("Parola actuală este greșită.")
    _verifica_parola(parola_noua)
    utilizator.parola_hash = generate_password_hash(parola_noua)
    jurnal.scrie(session, actor, "PAROLA_SCHIMBATA", "utilizator", utilizator.id)
    session.commit()
