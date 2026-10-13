"""Șabloanele de text (tabela `sablon`), cu valori implicite până le modifică administratorul."""
from dataclasses import dataclass
from string import Formatter

from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.drepturi import Actor, cere_rol
from inventar.models.sabloane import Sablon


@dataclass(frozen=True)
class SablonImplicit:
    cod: str
    titlu: str
    corp: str
    subiect: str | None = None
    ajutor: str = ""


PUNCTE = "." * 105
DECLARATIE_INCEPUT = f"""(1) Toate valorile materiale şi băneşti aflate în gestiunea subsemnatului se găsesc în încăperile:
{PUNCTE}
(2) Posed (nu posed) valori materiale şi băneşti aparţinând terţilor
{PUNCTE}
(3) Am (nu am) cunoştinţă de existenţa unor plusuri sau minusuri în valoare (cantitate) de
{PUNCTE}
(4) Am (nu am) eliberat valori materiale şi băneşti fără documente legale.
Beneficiar {"." * 94}
Beneficiar {"." * 94}
Beneficiar {"." * 94}
(5) Am (nu am) valori materiale nerecepţionate sau care trebuie expediate, pentru care s-au întocmit documentele aferente în cantitate de:
{PUNCTE}
(6) Am (nu am) documente de primire/eliberare care nu au fost operate în evidenţa operativă sau nu au fost predate la contabilitate:
{PUNCTE}
(7) Deţin (nu deţin) numerar din vânzarea mărfurilor aflate în gestiune, de lei:
{PUNCTE}
(8) Ultimele documente de intrare sunt:
felul ............. nr. ................ din data de ................................
felul ............. nr. ................ din data de ................................
(9) Ultimele documente de ieşire sunt:
felul ............. nr. ................ din data de ................................
felul ............. nr. ................ din data de ................................
(10) Ultimul raport de gestiune a fost încheiat la data de ...................... pentru perioada .............
(11) Dacă mai aveţi ceva de adăugat {"." * 70}
{PUNCTE}
{PUNCTE}"""

EMAIL_CORP = """Bună ziua, {nume},

Vă transmitem în atașament listele de inventariere la data de {data}, pentru gestiunile dumneavoastră ({locatie}).

Vă rugăm să le verificați și să ne semnalați eventualele neconcordanțe.

Cu stimă,
Comisia de inventariere"""

CAMPURI_EMAIL = ("nume", "data", "locatie")

SABLOANE = {
    "email_inventar": SablonImplicit(
        "email_inventar", "E-mailul cu listele de inventariere", EMAIL_CORP,
        subiect="Liste de inventariere la data de {data}",
        ajutor="Câmpuri disponibile, în subiect și în text: {nume} (titularul), {data} (data inventarului), "
               "{locatie} (locațiile gestiunilor lui).",
    ),
    "declaratie_inceput": SablonImplicit(
        "declaratie_inceput", "Declarația de inventar — punctele (1)–(11)", DECLARATIE_INCEPUT,
        ajutor="Fiecare rând apare ca atare în declarație. Punctele 8–9 rămân necompletate (se scriu de mână).",
    ),
}


def citeste_sablon(session: Session, cod: str) -> tuple[str | None, str]:
    """(subiect, corp): valoarea salvată sau, dacă nu există, cea implicită."""
    salvat = session.get(Sablon, cod)
    if salvat is not None:
        return salvat.subiect, salvat.corp
    implicit = SABLOANE[cod]
    return implicit.subiect, implicit.corp


def salveaza_sablon(session: Session, actor: Actor, cod: str, subiect: str | None, corp: str) -> None:
    cere_rol(actor, "ADMIN")
    if cod not in SABLOANE:
        raise EroareValidare("Șablon necunoscut.")
    corp = corp.replace("\r\n", "\n").strip("\n")
    if not corp.strip():
        raise EroareValidare("Textul șablonului nu poate fi gol.")
    if cod == "email_inventar":
        verifica_campuri(f"{subiect or ''}\n{corp}", CAMPURI_EMAIL)
    vechi_subiect, vechi_corp = citeste_sablon(session, cod)
    if (vechi_subiect, vechi_corp) == (subiect, corp):
        return
    sablon = session.get(Sablon, cod) or Sablon(cod=cod)
    sablon.subiect, sablon.corp = subiect, corp
    session.add(sablon)
    jurnal.scrie(session, actor, "SABLON_MODIFICAT", "sablon", None, {"cod": cod})
    session.commit()


def reseteaza_sablon(session: Session, actor: Actor, cod: str) -> None:
    cere_rol(actor, "ADMIN")
    sablon = session.get(Sablon, cod)
    if sablon is not None:
        session.delete(sablon)
        jurnal.scrie(session, actor, "SABLON_RESETAT", "sablon", None, {"cod": cod})
        session.commit()


def verifica_campuri(text: str, permise: tuple[str, ...]) -> None:
    """Un câmp scris greșit ({nme}) ar ajunge ca atare în sute de e-mailuri; se oprește la salvare."""
    try:
        campuri = {nume for _, nume, _, _ in Formatter().parse(text) if nume is not None}
    except ValueError:
        raise EroareValidare("Acolade nepotrivite în text; pentru o acoladă literală scrieți {{ sau }}.") from None
    necunoscute = campuri - set(permise)
    if necunoscute:
        raise EroareValidare(f"Câmpuri necunoscute: {', '.join(sorted(necunoscute))}. "
                             f"Sunt permise: {', '.join('{' + c + '}' for c in permise)}.")
