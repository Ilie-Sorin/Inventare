"""Backup zilnic al bazei SQLite, rulat din Task Scheduler.

    python scripts/backup.py --destinatie D:\\Backup\\Inventare [--pastreaza 30]

Copia se face cu API-ul online al SQLite (sqlite3.Connection.backup): e consistentă
și cât timp aplicația rulează și scrie. Lângă bază se copiază fișierele din instance/
fără de care o restaurare nu e completă: cheia de criptare a parolei SMTP, cheia
sesiunilor, sigla și configurarea. Codul de ieșire e nenul la orice eroare, ca
Task Scheduler să arate eșecul.
"""
import argparse
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

RADACINA = Path(__file__).resolve().parent.parent
FISIERE_INSTANTA = ("secret.key", "flask_secret.key", "sigla.png", "config.py")
PREFIX = "inventar_"

log = logging.getLogger("backup")


def cale_baza(instanta: Path) -> Path:
    """Aceeași regulă ca în aplicație: INVENTAR_DATABASE_URI sau instance/inventar.db."""
    uri = os.environ.get("INVENTAR_DATABASE_URI", "")
    if uri:
        if not uri.startswith("sqlite:///"):
            raise SystemExit(f"Backup-ul știe doar baze SQLite pe disc, nu {uri}.")
        return Path(urlparse(uri).path.lstrip("/") if os.name == "nt" else urlparse(uri).path)
    return instanta / "inventar.db"


def fa_backup(baza: Path, instanta: Path, destinatie: Path, acum: datetime | None = None) -> Path:
    if not baza.exists():
        raise FileNotFoundError(f"Baza de date nu există: {baza}")
    director = destinatie / f"{PREFIX}{(acum or datetime.now()):%Y-%m-%d_%H%M%S}"
    director.mkdir(parents=True, exist_ok=False)
    copie = director / baza.name
    sursa = sqlite3.connect(f"file:{baza.as_posix()}?mode=ro", uri=True)
    tinta = sqlite3.connect(copie)
    try:
        with tinta:
            sursa.backup(tinta)
        rezultat = tinta.execute("PRAGMA integrity_check").fetchone()[0]
        if rezultat != "ok":
            raise RuntimeError(f"Copia nu trece verificarea de integritate: {rezultat}")
        # Copia e un fișier unic, fără -wal / -shm alături.
        tinta.execute("PRAGMA journal_mode=DELETE")
    finally:
        sursa.close()
        tinta.close()
    for nume in FISIERE_INSTANTA:
        if (instanta / nume).exists():
            shutil.copy2(instanta / nume, director / nume)
    return director


def curata(destinatie: Path, pastreaza: int) -> list[Path]:
    """Păstrează cele mai recente `pastreaza` backup-uri; numele sortează cronologic."""
    toate = sorted(p for p in destinatie.glob(f"{PREFIX}*") if p.is_dir())
    vechi = toate[:-pastreaza] if pastreaza > 0 else []
    for director in vechi:
        shutil.rmtree(director)
    return vechi


def main(argumente: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup al bazei de date a aplicației de inventariere.")
    parser.add_argument("--destinatie", required=True, type=Path, help="directorul unde se păstrează backup-urile")
    parser.add_argument("--instanta", type=Path, default=RADACINA / "instance", help="directorul instance/")
    parser.add_argument("--pastreaza", type=int, default=30, help="câte backup-uri se păstrează (implicit 30)")
    a = parser.parse_args(argumente)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        director = fa_backup(cale_baza(a.instanta), a.instanta, a.destinatie)
        log.info("Backup făcut: %s", director)
        for vechi in curata(a.destinatie, a.pastreaza):
            log.info("Șters backup vechi: %s", vechi)
    except Exception:
        log.exception("Backup-ul a eșuat")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
