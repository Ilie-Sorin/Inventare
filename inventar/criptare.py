"""Criptarea parolei SMTP (Fernet). Cheia stă în instance/secret.key, separat de bază,
ca o copie a bazei de date să nu conțină parola în clar."""
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from inventar.domain.comun import EroareValidare

FISIER_CHEIE = "secret.key"


def _cheie(director_instanta: Path) -> bytes:
    fisier = director_instanta / FISIER_CHEIE
    if not fisier.exists():
        director_instanta.mkdir(parents=True, exist_ok=True)
        fisier.write_bytes(Fernet.generate_key())
    return fisier.read_bytes().strip()


def cripteaza(text: str, director_instanta: Path) -> str:
    return Fernet(_cheie(director_instanta)).encrypt(text.encode("utf-8")).decode("ascii")


def decripteaza(text_criptat: str, director_instanta: Path) -> str:
    """Șir gol dacă nu există parolă; eroare de validare dacă cheia nu mai corespunde (de ex. a fost înlocuită)."""
    if not text_criptat:
        return ""
    try:
        return Fernet(_cheie(director_instanta)).decrypt(text_criptat.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise EroareValidare("Parola SMTP nu poate fi decriptată (cheia din instance/secret.key s-a schimbat); "
                         "introduceți-o din nou în setări.") from None
