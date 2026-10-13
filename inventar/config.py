import os
from datetime import timedelta
from pathlib import Path


class Config:
    SECRET_KEY = os.environ.get("INVENTAR_SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = os.environ.get("INVENTAR_DATABASE_URI", "")
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # În producție aplicația e servită prin HTTPS (IIS / Caddy).
    SESSION_COOKIE_SECURE = os.environ.get("INVENTAR_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_DURATION = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = None
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024


def completeaza_implicite(config: dict, instance_path: str) -> None:
    """Completează ce n-a venit din instance/config.py sau din mediu.

    Cheia secretă se generează o singură dată și se păstrează în instance/,
    ca sesiunile să rămână valide după repornirea serviciului.
    """
    instance = Path(instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    if not config.get("SQLALCHEMY_DATABASE_URI"):
        config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{(instance / 'inventar.db').as_posix()}"
    if not config.get("SECRET_KEY"):
        fisier = instance / "flask_secret.key"
        if not fisier.exists():
            fisier.write_text(os.urandom(32).hex(), encoding="ascii")
        config["SECRET_KEY"] = fisier.read_text(encoding="ascii").strip()
