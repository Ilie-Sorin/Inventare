"""Manualul de utilizare: pagină statică, în română, vizibilă tuturor utilizatorilor autentificați."""
from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("ajutor", __name__)


@bp.route("/ajutor")
@login_required
def manual():
    return render_template("ajutor/manual.html")
