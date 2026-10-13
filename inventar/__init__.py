from flask import Flask, render_template
from flask_login import current_user

from inventar.config import Config, completeaza_implicite
from inventar.extensions import csrf, db, login_manager, migrate


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config is None:
        app.config.from_pyfile("config.py", silent=True)
    else:
        app.config.update(test_config)
    completeaza_implicite(app.config, app.instance_path)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.autentificare"
    login_manager.login_message = "Autentificați-vă pentru a continua."
    login_manager.login_message_category = "warning"

    from inventar import models  # noqa: F401 — înregistrează modelele pentru migrări

    @login_manager.user_loader
    def incarca_utilizator(user_id: str):
        return db.session.get(models.Utilizator, int(user_id))

    from inventar.web import (admin, auth, bunuri, comisii, documente, email, importuri, inventare,
                              nomenclatoare, persoane, principal, sincronizari)

    for modul in (admin, auth, bunuri, comisii, documente, email, importuri, inventare, nomenclatoare, persoane,
                  principal, sincronizari):
        app.register_blueprint(modul.bp)

    from inventar.drepturi import AccesInterzis, are_rol

    from inventar import formatare

    app.add_template_filter(formatare.data, "data_ro")
    app.add_template_filter(formatare.suma, "suma")

    @app.context_processor
    def drepturi_sablon():
        def poate(rol_minim: str) -> bool:
            return current_user.is_authenticated and are_rol(current_user.rol, rol_minim)
        return {"poate": poate}

    @app.errorhandler(AccesInterzis)
    def acces_interzis_serviciu(_eroare):
        db.session.rollback()
        return interzis(_eroare)

    from inventar.cli import inregistreaza_comenzi

    inregistreaza_comenzi(app)

    @app.errorhandler(403)
    def interzis(_eroare):
        return render_template("eroare.html", titlu="Acces interzis",
                               mesaj="Nu aveți drepturi pentru această pagină."), 403

    @app.errorhandler(404)
    def negasit(_eroare):
        return render_template("eroare.html", titlu="Pagină inexistentă",
                               mesaj="Pagina căutată nu există."), 404

    return app
