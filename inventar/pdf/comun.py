"""Elemente comune PDF-urilor: fonturi cu diacritice, numerotare „Pagina X din Y”, nume de fișiere."""
import re
import unicodedata
from pathlib import Path
from typing import Callable

from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.fonts import addMapping

DIRECTOR_FONTURI = Path(__file__).parent / "fonts"

# Familii: „DV” = DejaVu Sans, „DVC” = DejaVu Sans Condensed (pentru coloanele înguste).
FONT, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC = "DV", "DV-B", "DV-I", "DV-BI"
FONT_ING, FONT_ING_BOLD, FONT_ING_ITALIC = "DVC", "DVC-B", "DVC-I"

_FISIERE = {
    FONT: "DejaVuSans.ttf", FONT_BOLD: "DejaVuSans-Bold.ttf", FONT_ITALIC: "DejaVuSans-Oblique.ttf",
    FONT_BOLD_ITALIC: "DejaVuSans-BoldOblique.ttf", FONT_ING: "DejaVuSansCondensed.ttf",
    FONT_ING_BOLD: "DejaVuSansCondensed-Bold.ttf", FONT_ING_ITALIC: "DejaVuSansCondensed-Oblique.ttf",
}
_inregistrate = False


def inregistreaza_fonturi() -> None:
    """O singură dată pe proces: înregistrarea TTF-urilor e lentă, iar ReportLab le ține global."""
    global _inregistrate
    if _inregistrate:
        return
    for nume, fisier in _FISIERE.items():
        pdfmetrics.registerFont(TTFont(nume, str(DIRECTOR_FONTURI / fisier)))
    # Pentru <b>/<i> din Paragraph-urile declarațiilor.
    addMapping(FONT, 0, 0, FONT)
    addMapping(FONT, 1, 0, FONT_BOLD)
    addMapping(FONT, 0, 1, FONT_ITALIC)
    addMapping(FONT, 1, 1, FONT_BOLD_ITALIC)
    _inregistrate = True


def imparte(text: str, font: str, marime: float, latime: float) -> list[str]:
    return simpleSplit(text or "", font, marime, latime) or [""]


def potriveste(text: str, font: str, marime: float, latime: float, minim: float = 4.5) -> float:
    """Micșorează fontul până când textul încape pe un rând (nume lungi de gestiuni, comisii)."""
    while marime > minim and pdfmetrics.stringWidth(text, font, marime) > latime:
        marime -= 0.25
    return marime


def nume_fisier(*parti: str) -> str:
    """Nume sigur pentru sistemul de fișiere: fără diacritice, fără spații."""
    text = "_".join(parti)
    fara_diacritice = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", fara_diacritice).strip("_") + ".pdf"


def canvas_numerotat(subsol: Callable[[canvas.Canvas, int, int], None]) -> type:
    """Pânză care amână desenarea subsolului până se știe numărul total de pagini.

    Fiecare pagină se memorează la showPage(); la save() se redesenează toate,
    de data asta cu „Pagina X din Y” corect pentru întregul fișier (tot tirajul).
    """

    class CanvasNumerotat(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pagini: list[dict] = []

        def showPage(self):
            self._pagini.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pagini)
            for numar, stare in enumerate(self._pagini, start=1):
                self.__dict__.update(stare)
                subsol(self, numar, total)
                super().showPage()
            super().save()

    return CanvasNumerotat
