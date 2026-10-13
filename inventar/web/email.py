"""E-mail: previzualizare, confirmare, starea trimiterii, retrimitere, setări SMTP."""
import threading
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import select

from inventar.domain.comun import EroareValidare
from inventar.drepturi import Actor
from inventar.email import trimitere
from inventar.email.smtp import SECURITATE, are_parola, citeste_smtp, salveaza_smtp
from inventar.extensions import db
from inventar.models import TrimitereEmail
from inventar.web import actor_curent, arata_eroare, este_htmx, rol_necesar
from inventar.web.inventare import argumente_filtru, filtru_din_cerere

bp = Blueprint("email", __name__)

# Loturile pentru care rulează acum un fir de trimitere (în procesul curent).
_active: set[str] = set()
_lacat = threading.Lock()


def _director() -> Path:
    return Path(current_app.instance_path)


def porneste_firul(lot: str, actor: Actor) -> None:
    """Trimiterea durează (atașamente + SMTP), deci rulează separat; pagina lotului urmărește progresul."""
    app = current_app._get_current_object()
    director = _director()

    def lucru() -> None:
        with app.app_context():
            try:
                trimitere.trimite_lot(db.session, actor, lot, director)
            finally:
                db.session.remove()
                with _lacat:
                    _active.discard(lot)

    with _lacat:
        if lot in _active:
            return
        _active.add(lot)
    if app.config.get("EMAIL_SINCRON"):  # testele rulează trimiterea pe loc
        lucru()
    else:
        threading.Thread(target=lucru, name=f"email-{lot}", daemon=True).start()


@bp.route("/inventare/<int:inventar_id>/email", methods=["GET", "POST"])
@rol_necesar("OPERATOR")
def previzualizare(inventar_id: int):
    filtru = filtru_din_cerere()
    if request.method == "POST":
        try:
            lot = trimitere.porneste(db.session, actor_curent(), inventar_id, _director(), filtru)
        except EroareValidare as e:
            arata_eroare(e)
        else:
            porneste_firul(lot, actor_curent())
            flash("Trimiterea a pornit.", "success")
            return redirect(url_for(".lot", lot=lot))
    try:
        p = trimitere.previzualizare(db.session, inventar_id, filtru)
    except EroareValidare as e:
        arata_eroare(e)
        return redirect(url_for("inventare.detalii", inventar_id=inventar_id))
    exemplu = p.destinatari[0] if p.destinatari else None
    return render_template(
        "email/previzualizare.html", p=p, argumente=argumente_filtru(),
        smtp_configurat=citeste_smtp(db.session, _director(), cu_parola=False).configurat,
        subiect=trimitere.completeaza(p.subiect, exemplu, p.inventar) if exemplu else p.subiect,
        corp=trimitere.completeaza(p.corp, exemplu, p.inventar) if exemplu else p.corp,
    )


@bp.route("/email")
@login_required
def loturi():
    return render_template("email/loturi.html", loturi=trimitere.sumar_loturi(db.session))


@bp.route("/email/<lot>")
@login_required
def lot(lot: str):
    randuri = db.session.scalars(select(TrimitereEmail).where(TrimitereEmail.lot == lot)
                                 .order_by(TrimitereEmail.id)).all()
    if not randuri:
        return redirect(url_for(".loturi"))
    with _lacat:
        activ = lot in _active
    sablon = "email/_stare.html" if este_htmx() else "email/lot.html"
    return render_template(sablon, lot=lot, randuri=randuri, activ=activ,
                           in_asteptare=sum(r.stare == "IN_ASTEPTARE" for r in randuri),
                           erori=sum(r.stare == "EROARE" for r in randuri))


@bp.route("/email/<lot>/retrimitere", methods=["POST"])
@rol_necesar("OPERATOR")
def retrimitere(lot: str):
    with _lacat:
        activ = lot in _active
    if activ:
        flash("Trimiterea acestui lot încă rulează.", "warning")
        return redirect(url_for(".lot", lot=lot))
    try:
        # Rândurile rămase în așteptare fără fir activ au fost întrerupte (de ex. repornirea serviciului).
        numar = trimitere.pregateste_retrimiterea(db.session, actor_curent(), lot, include_intrerupte=True)
    except EroareValidare as e:
        arata_eroare(e)
    else:
        porneste_firul(lot, actor_curent())
        flash(f"Se retrimite la {numar} destinatari.", "success")
    return redirect(url_for(".lot", lot=lot))


@bp.route("/admin/email", methods=["GET", "POST"])
@rol_necesar("ADMIN")
def setari_smtp():
    if request.method == "POST":
        f = request.form
        try:
            if f.get("actiune") == "test":
                trimitere.trimite_test(db.session, actor_curent(), _director(), f.get("adresa_test", "").strip())
                flash("Mesajul de probă a fost trimis.", "success")
            else:
                salveaza_smtp(db.session, actor_curent(), _director(), server=f.get("server", ""),
                              port=int(f.get("port") or 0), securitate=f.get("securitate", ""),
                              utilizator=f.get("utilizator", ""), parola=f.get("parola") or None,
                              sterge_parola=bool(f.get("sterge_parola")), expeditor=f.get("expeditor", ""),
                              nume_expeditor=f.get("nume_expeditor", ""))
                flash("Setările SMTP au fost salvate.", "success")
        except ValueError as e:  # include EroareValidare și portul necompletat corect
            arata_eroare(e if isinstance(e, EroareValidare) else EroareValidare("Portul trebuie să fie un număr."))
        else:
            return redirect(url_for(".setari_smtp"))
    return render_template("email/smtp.html", setari=citeste_smtp(db.session, _director(), cu_parola=False),
                           are_parola=are_parola(db.session), securitati=SECURITATE)
