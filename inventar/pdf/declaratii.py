"""Declarația de inventar (de început, §10.2) și declarația de sfârșit de inventar (§10.3).

Ambele sunt pe gestiune × categorie și se semnează de titular (persoana fizică).
"""
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from inventar.formatare import data_in_litere
from inventar.pdf.comun import FONT, FONT_BOLD, FONT_ITALIC, inregistreaza_fonturi

# (eticheta din antet, genitiv pentru „utilizator al …”, forma din declarația de sfârșit)
CATEGORII = {
    "MF": ("Mijloace Fixe", "mijloacelor fixe", "mijloace fixe"),
    "OI": ("Obiecte de Inventar", "obiectelor de inventar", "obiecte de inventar"),
}


@dataclass
class Declaratie:
    categorie: str
    gestiune: str
    titular: str
    locatie: str
    comisie: list[str]


@dataclass
class AntetDeclaratii:
    data: date
    rand1: str  # ex. „Agenţia Naţională de Administrare Fiscală”
    rand2: str  # ex. „DGRFP IAŞI - A.J.F.P. Botoşani”
    unitate: str


def _stiluri(marime: float = 10) -> dict[str, ParagraphStyle]:
    baza = ParagraphStyle("baza", fontName=FONT, fontSize=marime, leading=marime * 1.3)
    return {
        "baza": baza,
        "colt": ParagraphStyle("colt", parent=baza, fontName=FONT_ITALIC, fontSize=7.5, alignment=TA_RIGHT),
        "antet": ParagraphStyle("antet", parent=baza, fontName=FONT_BOLD, fontSize=11, leading=15),
        "titlu": ParagraphStyle("titlu", parent=baza, fontName=FONT_BOLD, fontSize=12, alignment=TA_CENTER,
                                spaceBefore=18, spaceAfter=18),
        "centru": ParagraphStyle("centru", parent=baza, alignment=TA_CENTER),
        "nume": ParagraphStyle("nume", parent=baza, fontName=FONT_ITALIC, fontSize=8, leading=10,
                               alignment=TA_CENTER),
        "punct": ParagraphStyle("punct", parent=baza, fontSize=9.5, leading=12.5),
        "lista": ParagraphStyle("lista", parent=baza, leftIndent=40, firstLineIndent=-8),
    }


def _colt(d: Declaratie) -> str:
    """Colțul din dreapta sus; la gestiunile secundare numele gestiunii le deosebește declarațiile."""
    text = f"{d.locatie} - {CATEGORII[d.categorie][0]}"
    return text if d.gestiune == d.titular else f"{text} - gestiunea {d.gestiune}"


def _antet(d: Declaratie, antet: AntetDeclaratii, s: dict, titlu: str) -> list:
    return [
        Paragraph(escape(_colt(d)), s["colt"]),
        Paragraph(escape(antet.rand1), s["antet"]),
        Paragraph(escape(antet.rand2), s["antet"]),
        Paragraph(titlu, s["titlu"]),
    ]


def _semnaturi(stanga: tuple[str, str], dreapta: tuple[str, str], s: dict, latimi: list[float]) -> Table:
    tabel = Table(
        [[Paragraph(escape(stanga[0]), s["centru"]), Paragraph(escape(dreapta[0]), s["centru"])],
         [Paragraph(escape(stanga[1]), s["nume"]), Paragraph(escape(dreapta[1]), s["nume"])]],
        colWidths=latimi,
    )
    tabel.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return tabel


def deseneaza_declaratii_inceput(declaratii: list[Declaratie], antet: AntetDeclaratii, puncte: str) -> bytes:
    """O declarație pe pagină A4 portret. Textul punctelor (1)–(11) vine din șablon."""
    inregistreaza_fonturi()
    s = _stiluri()
    continut = BytesIO()
    doc = SimpleDocTemplate(continut, pagesize=A4, leftMargin=55, rightMargin=50, topMargin=40, bottomMargin=40,
                            title=f"Declarații de inventar {antet.data:%d.%m.%Y}", author=antet.unitate)
    poveste: list = []
    for i, d in enumerate(declaratii):
        if i:
            poveste.append(PageBreak())
        _, genitiv, _ = CATEGORII[d.categorie]
        poveste += _antet(d, antet, s, "DECLARAŢIE DE INVENTAR")
        poveste.append(Paragraph(
            f"Subsemnatul {escape(d.titular)}, în calitate de gestionar / utilizator al {genitiv} declar:", s["baza"]))
        poveste.append(Spacer(1, 10))
        poveste += [Paragraph(escape(rand) or "&nbsp;", s["punct"]) for rand in puncte.split("\n")]
        poveste += [Spacer(1, 22), Paragraph("Semnaturi:", s["baza"]), Spacer(1, 8)]
        poveste.append(_semnaturi(("DATĂ ÎN FAŢA NOASTRĂ:", ", ".join(d.comisie)), ("GESTIONAR", d.titular), s,
                                  [300, 190]))
        poveste += [Spacer(1, 30), Paragraph(f"Data: {data_in_litere(antet.data)}", s["baza"])]
    doc.build(poveste)
    return continut.getvalue()


def deseneaza_declaratii_sfarsit(declaratii: list[Declaratie], antet: AntetDeclaratii) -> bytes:
    """Două declarații pe o pagină A4: fiecare ocupă o jumătate."""
    inregistreaza_fonturi()
    s = _stiluri()
    latime, inaltime = A4
    continut = BytesIO()
    doc = BaseDocTemplate(continut, pagesize=A4, title=f"Declarații de sfârșit de inventar {antet.data:%d.%m.%Y}",
                          author=antet.unitate)
    jumatate = (inaltime - 60) / 2
    cadre = [Frame(50, 30 + jumatate, latime - 100, jumatate, id="sus"),
             Frame(50, 30, latime - 100, jumatate, id="jos")]
    doc.addPageTemplates([PageTemplate(id="doua", frames=cadre)])
    poveste: list = []
    for i, d in enumerate(declaratii):
        if i:
            poveste.append(FrameBreak())
        _, _, forma = CATEGORII[d.categorie]
        poveste += _antet(d, antet, s, "DECLARAŢIE DE SFÂRŞIT DE INVENTAR")
        poveste.append(Paragraph(
            f"Subsemnatul {escape(d.titular)} gestionar / utilizator al depozitului / gestiunii {forma} din cadrul "
            f"{escape(antet.unitate)} locaţia {escape(d.locatie)} declar că:",
            ParagraphStyle("intro", parent=s["baza"], firstLineIndent=30)))
        poveste.append(Spacer(1, 8))
        for punct in ("toate bunurile din gestiune AU FOST / NU AU FOST inventariate şi consemnate în listele de "
                      "inventar în prezenţa mea;",
                      "am / nu am obiecţii cu privire la modul în care s-a efectuat inventarierea."):
            poveste.append(Paragraph(f"● {punct}", s["lista"]))
        poveste.append(Spacer(1, 22))
        poveste.append(_semnaturi(("Gestionar,", d.titular), ("Comisia de Inventar:", ", ".join(d.comisie)), s,
                                  [170, 320]))
        poveste += [Spacer(1, 26), Paragraph(f"Data: {data_in_litere(antet.data)}", s["baza"])]
    doc.build(poveste)
    return continut.getvalue()
