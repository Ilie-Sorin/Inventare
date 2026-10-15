"""Documentul de mișcare (intrare, transfer, ieșire): A4 portret, cu semnăturile Predă / Primește.

Titlul este generic („Bon de mișcare”), fără cod de formular: nu am o cerință legală
precizată pentru un formular anume, iar textul se poate schimba ușor aici.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from inventar.formatare import data as data_ro
from inventar.formatare import suma
from inventar.pdf.comun import FONT, FONT_BOLD, FONT_ITALIC, canvas_numerotat, inregistreaza_fonturi

TITLURI = {
    "INTRARE": "BON DE MIȘCARE - INTRARE (REPARTIZARE)",
    "TRANSFER": "BON DE MIȘCARE - TRANSFER",
    "IESIRE": "BON DE MIȘCARE - IEȘIRE DIN EVIDENȚĂ",
}


@dataclass
class Parte:
    """Gestiunea care predă sau primește, cu locația și activitatea la data documentului."""
    gestiune: str
    titular: str
    locatie: str
    activitate: str


@dataclass
class RandDocument:
    nr_inventar: str
    nr_inventar_vechi: str | None
    denumire: str
    serie: str | None
    um: str
    categorie: str
    cont: str
    pret: Decimal
    casare: str | None = None  # „nr. 12 / 05.03.2025”, doar la ieșiri


@dataclass
class DocumentMiscare:
    tip: str
    serie: str | None
    numar: str
    data: date
    unitate: str
    unitate_superioara: str
    explicatie: str | None
    motiv_iesire: str | None
    de_la: list[Parte]
    la: list[Parte]
    randuri: list[RandDocument] = field(default_factory=list)
    intocmit_de: str = ""


def _stiluri() -> dict[str, ParagraphStyle]:
    baza = ParagraphStyle("baza", fontName=FONT, fontSize=9, leading=11.5)
    return {
        "baza": baza,
        "antet": ParagraphStyle("antet", parent=baza, fontName=FONT_BOLD, fontSize=10),
        "titlu": ParagraphStyle("titlu", parent=baza, fontName=FONT_BOLD, fontSize=13, leading=17,
                                alignment=TA_CENTER, spaceBefore=14, spaceAfter=4),
        "centru": ParagraphStyle("centru", parent=baza, alignment=TA_CENTER),
        "mic": ParagraphStyle("mic", parent=baza, fontSize=7, leading=8.5, fontName=FONT_ITALIC),
        "dreapta": ParagraphStyle("dreapta", parent=baza, alignment=TA_RIGHT),
        "nume": ParagraphStyle("nume", parent=baza, fontName=FONT_ITALIC, fontSize=8, alignment=TA_CENTER),
    }


def _text_parti(parti: list[Parte]) -> str:
    """O gestiune pe rând; titularul apare doar dacă diferă de numele gestiunii."""
    rezultat = []
    for p in parti:
        rand = f"<b>{escape(p.gestiune)}</b>"
        if p.titular and p.titular != p.gestiune:
            rand += f" (titular {escape(p.titular)})"
        rezultat.append(f"{rand}<br/>{escape(p.locatie)} / {escape(p.activitate)}")
    return "<br/>".join(rezultat) or "—"


def _semnatari(parti: list[Parte]) -> str:
    nume = dict.fromkeys(p.titular or p.gestiune for p in parti)  # păstrează ordinea, fără dubluri
    return ", ".join(nume)


def deseneaza_document(doc: DocumentMiscare) -> bytes:
    inregistreaza_fonturi()
    s = _stiluri()
    nr = f"{doc.serie} {doc.numar}".strip() if doc.serie else doc.numar
    titlu_pdf = f"{TITLURI[doc.tip]} nr. {nr} din {data_ro(doc.data)}"

    def subsol(c: Canvas, numar: int, total: int) -> None:
        c.setFont(FONT, 7.5)
        c.drawString(40, 24, f"Pagina {numar} din {total}")
        c.drawRightString(A4[0] - 40, 24, f"Bon de mișcare nr. {nr} din {data_ro(doc.data)}")

    continut = BytesIO()
    sablon = SimpleDocTemplate(continut, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=44,
                               title=titlu_pdf, author=doc.unitate)
    poveste: list = [
        Paragraph(escape(doc.unitate_superioara), s["antet"]),
        Paragraph(f"Unitatea: {escape(doc.unitate)}", s["antet"]),
        Paragraph(TITLURI[doc.tip], s["titlu"]),
        Paragraph(f"nr. {escape(nr)} din {data_ro(doc.data)}", s["centru"]),
        Spacer(1, 12),
    ]

    cap = [["Predă (de la)" if doc.de_la else "", "Primește (la)" if doc.la else ""],
           [Paragraph(_text_parti(doc.de_la), s["baza"]) if doc.de_la else "",
            Paragraph(_text_parti(doc.la), s["baza"]) if doc.la else ""]]
    parti = Table(cap, colWidths=[257, 258])
    parti.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), FONT_BOLD, 8.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    poveste += [parti, Spacer(1, 8)]
    if doc.motiv_iesire:
        poveste.append(Paragraph(f"<b>Motivul ieșirii:</b> {escape(doc.motiv_iesire)}", s["baza"]))
    if doc.explicatie:
        poveste.append(Paragraph(f"<b>Explicație:</b> {escape(doc.explicatie)}", s["baza"]))
    poveste.append(Spacer(1, 8))

    antet_tabel = ["Nr.\ncrt.", "Denumirea bunului", "Nr. inventar", "Cont", "U/M", "Cant.", "Valoare\n(lei)"]
    date_tabel: list = [antet_tabel]
    for i, r in enumerate(doc.randuri, start=1):
        denumire = escape(r.denumire)
        if r.serie:
            denumire += f"<br/><font size='7'>Serie: {escape(r.serie)}</font>"
        if r.casare:
            denumire += f"<br/><font size='7'>Casare {escape(r.casare)}</font>"
        nr_inv = escape(r.nr_inventar)
        if r.nr_inventar_vechi:
            nr_inv += f"<br/><font size='7'><i>(vechi {escape(r.nr_inventar_vechi)})</i></font>"
        date_tabel.append([str(i), Paragraph(denumire, s["baza"]), Paragraph(nr_inv, s["baza"]), r.cont, r.um,
                           "1,00", suma(r.pret, separator_mii=False)])
    total = sum((r.pret for r in doc.randuri), start=Decimal(0))
    date_tabel.append(["", f"TOTAL: {len(doc.randuri)} bunuri", "", "", "", "", suma(total, separator_mii=False)])
    tabel = Table(date_tabel, colWidths=[28, 235, 75, 70, 30, 32, 45], repeatRows=1)
    tabel.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), FONT, 8.5), ("FONT", (0, 0), (-1, 0), FONT_BOLD, 8),
        ("FONT", (0, -1), (-1, -1), FONT_BOLD, 8.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"), ("ALIGN", (5, 1), (6, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("SPAN", (1, -1), (5, -1)),
    ]))
    poveste.append(tabel)
    poveste.append(Spacer(1, 30))

    semnaturi = Table(
        [["Predă", "Primește"],
         [Paragraph(escape(_semnatari(doc.de_la)) or "&nbsp;", s["nume"]),
          Paragraph(escape(_semnatari(doc.la)) or "&nbsp;", s["nume"])],
         ["Semnătura", "Semnătura"]],
        colWidths=[257, 258], rowHeights=[16, 34, 14])
    semnaturi.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONT", (0, 0), (-1, 0), FONT_BOLD, 9),
        ("FONT", (0, 2), (-1, 2), FONT_ITALIC, 7.5), ("VALIGN", (0, 1), (-1, 1), "BOTTOM"),
    ]))
    poveste.append(semnaturi)
    if doc.intocmit_de:
        poveste += [Spacer(1, 18), Paragraph(f"Întocmit de: {escape(doc.intocmit_de)}", s["mic"])]
    sablon.build(poveste, canvasmaker=canvas_numerotat(subsol))
    return continut.getvalue()
