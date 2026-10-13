"""Setările aplicației (tabela `setare`): textele din antete, sigla, nivelul contului."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.drepturi import Actor, cere_rol
from inventar.models import Setare


@dataclass(frozen=True)
class DefinitieSetare:
    cheie: str
    eticheta: str
    implicit: str = ""
    ajutor: str = ""


SETARI = (
    DefinitieSetare("unitate_superioara", "Unitatea superioară", ajutor="Ex.: D.G.R.F.P. IASI (antetul listei)"),
    DefinitieSetare("unitate", "Unitatea", ajutor="Ex.: A.J.F.P. BOTOSANI (antetul listei)"),
    DefinitieSetare("antet_declaratii_1", "Antet declarații — rândul 1",
                    ajutor="Ex.: Agenţia Naţională de Administrare Fiscală"),
    DefinitieSetare("antet_declaratii_2", "Antet declarații — rândul 2",
                    ajutor="Ex.: DGRFP IAŞI - A.J.F.P. Botoşani"),
    DefinitieSetare("nivel_cont_margine", "Nivelul contului în marginea listei", "2",
                    ajutor="Câte niveluri ale contului apar în margine: 1 = 303, 2 = 303.02, 3 = 303.02.00"),
)
_CHEI = {s.cheie: s for s in SETARI}

FISIER_SIGLA = "sigla.png"


def citeste_setari(session: Session) -> dict[str, str]:
    valori = {s.cheie: s.implicit for s in SETARI}
    valori["sigla"] = ""
    for setare in session.scalars(select(Setare)):
        valori[setare.cheie] = setare.valoare
    return valori


def _valideaza(cheie: str, valoare: str) -> str:
    valoare = valoare.strip()
    if cheie == "nivel_cont_margine" and valoare not in {"1", "2", "3", "4"}:
        raise EroareValidare("Nivelul contului trebuie să fie între 1 și 4.")
    return valoare


def _scrie(session: Session, cheie: str, valoare: str) -> str | None:
    """Întoarce valoarea veche dacă s-a schimbat ceva, altfel None."""
    setare = session.get(Setare, cheie)
    vechi = setare.valoare if setare else (_CHEI[cheie].implicit if cheie in _CHEI else "")
    if vechi == valoare:
        return None
    if setare is None:
        session.add(Setare(cheie=cheie, valoare=valoare))
    else:
        setare.valoare = valoare
    return vechi


def salveaza_setari(session: Session, actor: Actor, valori: dict[str, str]) -> None:
    cere_rol(actor, "ADMIN")
    schimbari = {}
    for cheie, valoare in valori.items():
        if cheie not in _CHEI:
            raise EroareValidare(f"Setare necunoscută: {cheie}.")
        valoare = _valideaza(cheie, valoare)
        vechi = _scrie(session, cheie, valoare)
        if vechi is not None:
            schimbari[cheie] = [vechi, valoare]
    if schimbari:
        jurnal.scrie(session, actor, "SETARI_MODIFICATE", detalii=schimbari)
    session.commit()


def salveaza_sigla(session: Session, actor: Actor, continut: bytes, director: Path) -> None:
    """Sigla se normalizează la PNG, ca ReportLab s-o poată folosi fără surprize de format."""
    cere_rol(actor, "ADMIN")
    try:
        imagine = Image.open(BytesIO(continut))
        imagine.load()
    except Exception:
        raise EroareValidare("Fișierul încărcat nu este o imagine validă (PNG sau JPG).")
    if imagine.mode not in ("RGB", "RGBA"):
        imagine = imagine.convert("RGBA")
    director.mkdir(parents=True, exist_ok=True)
    imagine.save(director / FISIER_SIGLA, format="PNG")
    _scrie(session, "sigla", FISIER_SIGLA)
    jurnal.scrie(session, actor, "SIGLA_INCARCATA", detalii={"latime": imagine.width, "inaltime": imagine.height})
    session.commit()
