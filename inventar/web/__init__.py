from functools import wraps
from typing import Callable

from flask import abort, flash, request
from flask_login import current_user, login_required

from inventar.domain.comun import EroareValidare
from inventar.drepturi import Actor, are_rol
from inventar.extensions import db


def actor_curent() -> Actor:
    return Actor(
        utilizator_id=current_user.id,
        username=current_user.username,
        rol=current_user.rol,
        ip=request.remote_addr,
    )


def rol_necesar(rol_minim: str) -> Callable:
    """Decorator pentru rute; serviciile verifică și ele rolul, separat."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if not are_rol(current_user.rol, rol_minim):
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def arata_eroare(eroare: EroareValidare) -> None:
    # Serviciul poate fi lăsat modificări neconfirmate în sesiune înainte să
    # descopere eroarea; ele nu trebuie să ajungă în baza de date.
    db.session.rollback()
    flash(str(eroare), "danger")


def este_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"
