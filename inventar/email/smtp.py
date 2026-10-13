"""Setările SMTP ale instituției și trimiterea propriu-zisă (smtplib, stdlib)."""
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.criptare import cripteaza, decripteaza
from inventar.domain.comun import EroareValidare
from inventar.drepturi import Actor, cere_rol
from inventar.models import Setare

SECURITATE = {"starttls": "STARTTLS (de obicei portul 587)", "ssl": "SSL/TLS (de obicei portul 465)",
              "niciuna": "Fără criptare (doar în rețeaua internă, de obicei portul 25)"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIMP_ASTEPTARE = 30


@dataclass(frozen=True)
class SetariSmtp:
    server: str
    port: int
    securitate: str
    utilizator: str
    parola: str
    expeditor: str
    nume_expeditor: str

    @property
    def configurat(self) -> bool:
        return bool(self.server and self.expeditor)


def _valoare(session: Session, cheie: str, implicit: str = "") -> str:
    setare = session.get(Setare, cheie)
    return setare.valoare if setare else implicit


def are_parola(session: Session) -> bool:
    return bool(_valoare(session, "smtp_parola"))


def citeste_smtp(session: Session, director_instanta: Path, cu_parola: bool = True) -> SetariSmtp:
    """`cu_parola=False` pentru afișare: parola nu se decriptează și nu ajunge în pagină."""
    return SetariSmtp(
        server=_valoare(session, "smtp_server"),
        port=int(_valoare(session, "smtp_port", "587") or 587),
        securitate=_valoare(session, "smtp_securitate", "starttls"),
        utilizator=_valoare(session, "smtp_utilizator"),
        parola=decripteaza(_valoare(session, "smtp_parola"), director_instanta) if cu_parola else "",
        expeditor=_valoare(session, "smtp_expeditor"),
        nume_expeditor=_valoare(session, "smtp_nume_expeditor"),
    )


def salveaza_smtp(session: Session, actor: Actor, director_instanta: Path, *, server: str, port: int,
                  securitate: str, utilizator: str, parola: str | None, sterge_parola: bool, expeditor: str,
                  nume_expeditor: str) -> None:
    """`parola=None` sau gol păstrează parola existentă; în jurnal nu ajunge niciodată parola."""
    cere_rol(actor, "ADMIN")
    if securitate not in SECURITATE:
        raise EroareValidare("Tip de securitate necunoscut.")
    if not 1 <= port <= 65535:
        raise EroareValidare("Portul trebuie să fie între 1 și 65535.")
    if expeditor and not _EMAIL.match(expeditor.strip()):
        raise EroareValidare("Adresa expeditorului nu este validă.")
    valori = {"smtp_server": server.strip(), "smtp_port": str(port), "smtp_securitate": securitate,
              "smtp_utilizator": utilizator.strip(), "smtp_expeditor": expeditor.strip(),
              "smtp_nume_expeditor": nume_expeditor.strip()}
    if sterge_parola:
        valori["smtp_parola"] = ""
    elif parola:
        valori["smtp_parola"] = cripteaza(parola, director_instanta)
    schimbate = []
    for cheie, valoare in valori.items():
        setare = session.get(Setare, cheie)
        if setare is None:
            session.add(Setare(cheie=cheie, valoare=valoare))
            schimbate.append(cheie)
        elif setare.valoare != valoare:
            setare.valoare = valoare
            schimbate.append(cheie)
    if schimbate:
        jurnal.scrie(session, actor, "SETARI_SMTP_MODIFICATE", detalii={"campuri": sorted(schimbate)})
    session.commit()


def construieste_mesaj(setari: SetariSmtp, adresa: str, subiect: str, corp: str,
                       atasamente: list[tuple[str, bytes]]) -> EmailMessage:
    mesaj = EmailMessage()
    mesaj["From"] = formataddr((setari.nume_expeditor, setari.expeditor)) if setari.nume_expeditor else setari.expeditor
    mesaj["To"] = adresa
    mesaj["Subject"] = subiect
    mesaj["Message-ID"] = make_msgid(domain=setari.expeditor.rsplit("@", 1)[-1])
    mesaj.set_content(corp)
    for nume, continut in atasamente:
        mesaj.add_attachment(continut, maintype="application", subtype="pdf", filename=nume)
    return mesaj


class Conexiune:
    """O conexiune SMTP refolosită pentru tot lotul; se redeschide dacă serverul o închide."""

    def __init__(self, setari: SetariSmtp):
        self.setari = setari
        self.smtp: smtplib.SMTP | None = None

    def _deschide(self) -> smtplib.SMTP:
        s = self.setari
        if s.securitate == "ssl":
            smtp = smtplib.SMTP_SSL(s.server, s.port, timeout=TIMP_ASTEPTARE, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(s.server, s.port, timeout=TIMP_ASTEPTARE)
            if s.securitate == "starttls":
                smtp.starttls(context=ssl.create_default_context())
        if s.utilizator:
            smtp.login(s.utilizator, s.parola)
        return smtp

    def trimite(self, mesaj: EmailMessage) -> None:
        if self.smtp is None:
            self.smtp = self._deschide()
        try:
            self.smtp.send_message(mesaj)
        except smtplib.SMTPServerDisconnected:
            self.smtp = self._deschide()
            self.smtp.send_message(mesaj)

    def inchide(self) -> None:
        if self.smtp is not None:
            try:
                self.smtp.quit()
            except smtplib.SMTPException:
                pass
            self.smtp = None
