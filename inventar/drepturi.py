"""Cine face o acțiune și ce are voie să facă.

Serviciile primesc un `Actor`, nu obiectul Flask-Login, ca să poată fi
apelate la fel din rute, din comenzi CLI și din teste.
"""
from dataclasses import dataclass

# Fiecare rol include drepturile celor de după el.
IERARHIE = {"ADMIN": 3, "OPERATOR": 2, "CONSULTARE": 1}


class AccesInterzis(Exception):
    pass


@dataclass(frozen=True)
class Actor:
    utilizator_id: int | None
    username: str
    rol: str
    ip: str | None = None


SISTEM = Actor(utilizator_id=None, username="sistem", rol="ADMIN")


def are_rol(rol_actor: str, rol_minim: str) -> bool:
    return IERARHIE.get(rol_actor, 0) >= IERARHIE[rol_minim]


def cere_rol(actor: Actor, rol_minim: str) -> None:
    if not are_rol(actor.rol, rol_minim):
        raise AccesInterzis(f"Acțiunea necesită rolul {rol_minim}.")
