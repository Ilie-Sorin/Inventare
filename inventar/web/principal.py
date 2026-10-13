from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("principal", __name__)


@bp.route("/")
@login_required
def acasa():
    return render_template("acasa.html")
