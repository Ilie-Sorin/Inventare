import click
from flask import Flask

from inventar import utilizatori
from inventar.drepturi import Actor
from inventar.extensions import db


def inregistreaza_comenzi(app: Flask) -> None:
    @app.cli.command("creeaza-admin")
    @click.option("--username", prompt="Utilizator", default="admin", show_default=True)
    @click.password_option("--parola", prompt="Parolă", confirmation_prompt="Confirmați parola")
    def creeaza_admin(username: str, parola: str) -> None:
        """Creează un utilizator cu rolul ADMIN."""
        actor = Actor(utilizator_id=None, username="cli", rol="ADMIN", ip="local")
        try:
            utilizatori.creeaza_utilizator(db.session, actor, username, parola, "ADMIN")
        except utilizatori.EroareUtilizator as e:
            raise click.ClickException(str(e))
        click.echo(f"Administratorul „{username}” a fost creat.")
