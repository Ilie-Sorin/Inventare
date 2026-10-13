"""Centralizatoarele în PDF: A4 portret, fără semnături (§11)."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from inventar.domain.centralizatoare import RandCentralizator
from inventar.formatare import data_in_litere, suma
from inventar.pdf.comun import FONT, FONT_BOLD, FONT_ITALIC, canvas_numerotat, inregistreaza_fonturi


def _subsol(c, pagina: int, total: int) -> None:
    c.setFont(FONT_ITALIC, 7)
    c.drawString(50, 25, f"Pagina {pagina} din {total}")


def deseneaza_centralizator(randuri: list[RandCentralizator], unitate: str, titlu: str, data: date,
                            filtru: str) -> bytes:
    inregistreaza_fonturi()
    continut = BytesIO()
    doc = SimpleDocTemplate(continut, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=45, bottomMargin=45,
                            title=titlu, author=unitate)
    baza = ParagraphStyle("baza", fontName=FONT, fontSize=9, leading=12)
    poveste: list = [
        Paragraph(escape(unitate), ParagraphStyle("u", parent=baza, fontName=FONT_BOLD)),
        Spacer(1, 10),
        Paragraph(escape(titlu), ParagraphStyle("t", parent=baza, fontName=FONT_BOLD, fontSize=13, leading=17)),
        Paragraph(f"Inventarul la data de {data_in_litere(data)}", baza),
        Paragraph(f"Filtru: {escape(filtru)}", ParagraphStyle("f", parent=baza, fontName=FONT_ITALIC, fontSize=8)),
        Spacer(1, 10),
    ]
    tabel = [["", "Număr bunuri", "Valoare"]]
    stil = [
        ("FONT", (0, 0), (-1, -1), FONT, 8.5),
        ("FONT", (0, 0), (-1, 0), FONT_BOLD, 8.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    for i, r in enumerate(randuri, start=1):
        tabel.append(["    " * r.nivel + r.eticheta, "" if r.numar is None else str(r.numar),
                      "" if r.valoare is None else suma(r.valoare)])
        if r.tip != "detaliu":
            stil.append(("FONT", (0, i), (-1, i), FONT_BOLD, 8.5))
        if r.tip == "subtotal":
            stil.append(("LINEABOVE", (1, i), (-1, i), 0.3, colors.grey))
        if r.tip == "total":
            stil.append(("LINEABOVE", (0, i), (-1, i), 0.8, colors.black))
    t = Table(tabel, colWidths=[300, 80, 115], repeatRows=1)
    t.setStyle(TableStyle(stil))
    poveste.append(t)
    doc.build(poveste, canvasmaker=canvas_numerotat(_subsol))
    return continut.getvalue()


def deseneaza_tabele(unitate: str, titlu: str, tabele: list[tuple[str, list[str], list[list]]]) -> bytes:
    """Rapoarte simple (ex. sincronizarea): A4 vedere, câte un tabel pe secțiune."""
    inregistreaza_fonturi()
    continut = BytesIO()
    doc = SimpleDocTemplate(continut, pagesize=landscape(A4), leftMargin=36, rightMargin=36, topMargin=36,
                            bottomMargin=40, title=titlu, author=unitate)
    baza = ParagraphStyle("baza", fontName=FONT, fontSize=8, leading=10)
    poveste: list = [Paragraph(escape(unitate), ParagraphStyle("u", parent=baza, fontName=FONT_BOLD, fontSize=9)),
                     Paragraph(escape(titlu), ParagraphStyle("t", parent=baza, fontName=FONT_BOLD, fontSize=13,
                                                             leading=18, spaceAfter=8))]
    for sectiune, antet, randuri in tabele:
        poveste.append(Paragraph(escape(sectiune), ParagraphStyle("s", parent=baza, fontName=FONT_BOLD, fontSize=10,
                                                                  spaceBefore=8, spaceAfter=4)))
        if not randuri:
            poveste.append(Paragraph("—", baza))
            continue
        date = [[Paragraph(escape(h), ParagraphStyle("h", parent=baza, fontName=FONT_BOLD)) for h in antet]]
        for rand in randuri:
            date.append([suma(v) if isinstance(v, Decimal) else Paragraph(escape(str(v)), baza) for v in rand])
        t = Table(date, repeatRows=1)
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), FONT, 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee"))]))
        poveste.append(t)
    doc.build(poveste, canvasmaker=canvas_numerotat(_subsol))
    return continut.getvalue()
