"""Lista de inventariere, formular 14-3-12, A4 vedere (§10.1).

O listă = o gestiune × un cont sintetic × o locație. Antetul, capul de tabel și
blocul de semnături se repetă pe fiecare pagină (normele cer semnarea fiecărei file);
„Pagina” din antet numără în cadrul listei, iar subsolul numără pe tot fișierul.
Desenăm direct pe pânză, cu paginare proprie: formularul are poziții fixe.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from inventar.formatare import data as data_ro
from inventar.formatare import data_in_litere, suma
from inventar.pdf.comun import (
    FONT,
    FONT_BOLD,
    FONT_BOLD_ITALIC,
    FONT_ING,
    FONT_ITALIC,
    canvas_numerotat,
    imparte,
    inregistreaza_fonturi,
    potriveste,
)

LATIME, INALTIME = landscape(A4)
X0, X1 = 48.0, LATIME - 18  # marginea stângă lasă loc contului și datei amortizării
SUS, JOS = INALTIME - 16, 22.0
# Lățimile coloanelor 0–14, după proporțiile modelului.
COLOANE = [20, 168, 58, 20] + [(X1 - X0 - 266) / 11] * 11
MARGINI = [X0]
for _l in COLOANE:
    MARGINI.append(MARGINI[-1] + _l)

CATEGORII = {"MF": ("Mijloace Fixe", "Mijloace Fixe"), "OI": ("Obiecte de inventar", "Ob. Inventar")}
MENTIUNE = ("Toate bunurile din gestiune au fost inventariate in prezenta mea si nu am obiectii "
            "cu privire la modul de efectuare a inventarierii.")


@dataclass
class RandLista:
    nr_inventar: str
    nr_inventar_vechi: str | None
    denumire: str
    serie: str | None
    um: str
    pret: Decimal
    cont: str
    data_amortizare_integrala: date | None


@dataclass
class Lista:
    categorie: str
    cont_sintetic: str
    gestiune: str
    titular: str
    locatie: str
    comisie: list[str]
    randuri: list[RandLista] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((r.pret for r in self.randuri), Decimal("0"))


@dataclass
class Antet:
    data: date
    unitate: str
    unitate_superioara: str
    sigla: Path | None
    nivel_cont: int = 2


def cont_in_margine(cont: str, nivel: int) -> str:
    return ".".join(cont.split(".")[:nivel])


# --- desen ---

def _text(c: Canvas, x: float, y: float, text: str, font: str, marime: float, aliniere: str = "stanga") -> None:
    c.setFont(font, marime)
    if aliniere == "dreapta":
        c.drawRightString(x, y, text)
    elif aliniere == "centru":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)


def _celula_centrata(c: Canvas, x0: float, x1: float, y0: float, y1: float, text: str, marime: float = 6.5,
                     font: str = FONT) -> None:
    """Text pe mai multe rânduri („\\n”), centrat în dreptunghi; dreptunghiul se trasează și el."""
    c.rect(x0, y0, x1 - x0, y1 - y0)
    randuri = text.split("\n") if text else []
    pas = marime + 1
    y = (y0 + y1) / 2 + (len(randuri) - 1) * pas / 2 - marime / 3
    for r in randuri:
        _text(c, (x0 + x1) / 2, y, r, font, potriveste(r, font, marime, x1 - x0 - 2), "centru")
        y -= pas


def _antet(c: Canvas, lista: Lista, antet: Antet, pagina: int) -> float:
    magazia, _ = CATEGORII[lista.categorie]
    _text(c, X1, SUS - 5, f"{magazia} - Cont: {lista.cont_sintetic}, Loc depozitare - {lista.locatie}, "
                          f"Gestionar: {lista.gestiune}", FONT_ITALIC, 5.5, "dreapta")
    sus, jos = SUS - 9, SUS - 55
    c.setLineWidth(0.8)
    c.rect(X0, jos, X1 - X0, sus - jos)
    c.setLineWidth(0.3)
    # Stânga: sigla și unitățile (din setări).
    x_text = X0 + 6
    if antet.sigla and antet.sigla.exists():
        imagine = ImageReader(str(antet.sigla))
        lat, inalt = imagine.getSize()
        h = 34.0
        w = min(h * lat / inalt, 110)
        c.drawImage(imagine, X0 + 4, jos + 6, width=w, height=w * inalt / lat, mask="auto")
        x_text = X0 + 10 + w
    _text(c, x_text, sus - 13, antet.unitate_superioara, FONT_BOLD, 9)
    _text(c, x_text, sus - 24, "Unitatea", FONT, 6.5)
    _text(c, x_text, sus - 36, antet.unitate, FONT_BOLD, 8)
    # Centru: titlul și data, cu luna în litere.
    centru = (MARGINI[4] + MARGINI[9]) / 2
    _text(c, centru, sus - 20, "LISTA DE INVENTARIERE", FONT_BOLD, 15, "centru")
    text_data = f"Data:  {data_in_litere(antet.data)}"
    _text(c, centru, sus - 36, text_data, FONT, 7.5, "centru")
    # Dreapta: magazia, gestiunea, locul de depozitare și pagina din listă.
    xr, xp = MARGINI[11] - 10, X1 - 28
    c.line(xr, jos, xr, sus)
    c.line(xp, jos, xp, sus)
    pas = (sus - jos) / 3
    for i, (eticheta, valoare) in enumerate((("Magazia", magazia), ("Gestiunea", lista.gestiune),
                                             ("Loc de depozitare", lista.locatie))):
        y = sus - pas * i - pas / 2 - 2.5
        _text(c, xr + 3, y, eticheta, FONT, 6.5)
        x_valoare = xr + 5 + stringWidth(eticheta, FONT, 6.5)
        _text(c, x_valoare, y, valoare, FONT_BOLD, potriveste(valoare, FONT_BOLD, 7.5, xp - x_valoare - 18))
    _text(c, xp - 3, sus - pas / 2 - 2.5, lista.cont_sintetic, FONT_BOLD_ITALIC, 7, "dreapta")
    _text(c, (xp + X1) / 2, sus - 12, "Pagina", FONT, 6.5, "centru")
    _text(c, (xp + X1) / 2, jos + 14, str(pagina), FONT, 8, "centru")
    return jos


def _cap_tabel(c: Canvas, sus: float) -> float:
    m, h = MARGINI, 11.0
    r1, r2, r3, r4 = sus, sus - h, sus - 2 * h, sus - 3 * h
    celule = [
        (0, 1, r1, r4, "Nr.\ncrt."), (1, 2, r1, r4, "Denumirea bunurilor inventariate"),
        (2, 3, r1, r4, "Codul sau\nnumarul de\ninventar"), (3, 4, r1, r4, "U/M"),
        (4, 8, r1, r2, "CANTITATI"), (4, 6, r2, r3, "Stocuri"), (6, 8, r2, r3, "Diferente"),
        (4, 5, r3, r4, "Scriptice"), (5, 6, r3, r4, "Faptice"), (6, 7, r3, r4, "Plus"), (7, 8, r3, r4, "Minus"),
        (8, 9, r1, r4, "PRET\nUNITAR"),
        (9, 12, r1, r2, "VALOAREA CONTABILA"), (9, 10, r2, r4, "Valoarea"), (10, 12, r2, r3, "Diferente"),
        (10, 11, r3, r4, "Plus"), (11, 12, r3, r4, "Minus"),
        (12, 13, r1, r4, "Valoarea\nde\ninventar"),
        (13, 15, r1, r2, "DEPRECIEREA"), (13, 14, r2, r4, "Valoarea"), (14, 15, r2, r4, "Motivul\n(cod)"),
    ]
    for a, b, y_sus, y_jos, text in celule:
        _celula_centrata(c, m[a], m[b], y_jos, y_sus, text, 5.5 if a == 2 else 6.5)
    jos = r4 - 9
    for i in range(15):
        _celula_centrata(c, m[i], m[i + 1], jos, r4, str(i), 6)
    return jos


def _masoara_rand(r: RandLista) -> tuple[list[str], float]:
    randuri = imparte(r.denumire, FONT_ING, 7, COLOANE[1] - 4)
    inaltime = len(randuri) * 8 + (7 if r.serie else 0) + 3
    return randuri, max(inaltime, 11)


def _rand(c: Canvas, sus: float, nr: int, r: RandLista, categorie: str, nivel_cont: int) -> float:
    m = MARGINI
    randuri_denumire, inaltime = _masoara_rand(r)
    jos = sus - inaltime
    y = sus - 8
    _text(c, m[1] - 2, y, str(nr), FONT, 7, "dreapta")
    for i, text in enumerate(randuri_denumire):
        _text(c, m[1] + 2, y - i * 8, text, FONT_ING, 7)
    if r.serie:
        _text(c, m[1] + 6, y - len(randuri_denumire) * 8 + 1,
              f"seria {r.serie}", FONT_ITALIC, potriveste(f"seria {r.serie}", FONT_ITALIC, 5.5, COLOANE[1] - 8))
    _text(c, m[2] + 2, y, r.nr_inventar, FONT_ING, 7)
    if r.nr_inventar_vechi:
        loc_alaturi = COLOANE[2] - 6 - stringWidth(r.nr_inventar, FONT_ING, 7)
        if stringWidth(r.nr_inventar_vechi, FONT_ITALIC, 5) <= loc_alaturi:
            _text(c, m[3] - 2, y, r.nr_inventar_vechi, FONT_ITALIC, 5, "dreapta")
        else:
            _text(c, m[3] - 2, y - 7, r.nr_inventar_vechi, FONT_ITALIC, 5, "dreapta")
    _text(c, (m[3] + m[4]) / 2, y, r.um, FONT, potriveste(r.um, FONT, 7, COLOANE[3] - 2), "centru")
    _text(c, m[5] - 2, y, "1,00", FONT, 7, "dreapta")
    pret = suma(r.pret, separator_mii=False)
    _text(c, m[9] - 2, y, pret, FONT, 7, "dreapta")
    _text(c, m[10] - 2, y, pret, FONT, 7, "dreapta")
    # Marginea stângă: contul (nivel configurabil) și, la MF, data amortizării integrale.
    _text(c, X0 - 3, y, cont_in_margine(r.cont, nivel_cont), FONT, 5, "dreapta")
    if categorie == "MF" and r.data_amortizare_integrala:
        _text(c, X0 - 3, y - 6, data_ro(r.data_amortizare_integrala), FONT, 4.5, "dreapta")
    for x in m:
        c.line(x, jos, x, sus)
    c.line(m[0], jos, m[-1], jos)
    return jos


INALTIME_FINAL = 14 + 38


def _final(c: Canvas, sus: float, lista: Lista) -> float:
    m = MARGINI
    _, responsabil = CATEGORII[lista.categorie]
    jos = sus - 14
    c.setLineWidth(0.8)
    c.rect(m[0], jos, m[-1] - m[0], 14)
    c.setLineWidth(0.3)
    for x in m[9:15]:
        c.line(x, jos, x, sus)
    eticheta = f"Total pentru gestiunea {lista.gestiune} / {lista.locatie}"
    _text(c, m[1] + 2, jos + 4.5, eticheta, FONT_BOLD, potriveste(eticheta, FONT_BOLD, 7.5, m[9] - m[1] - 6))
    _text(c, m[10] - 2, jos + 4.5, suma(lista.total, separator_mii=False), FONT_BOLD, 7.5, "dreapta")
    # Mențiunea gestionarului (pct. 33 din norme).
    sus, jos = jos, jos - 38
    c.rect(m[0], jos, m[-1] - m[0], sus - jos)
    _text(c, (m[0] + m[-1]) / 2, sus - 11, MENTIUNE, FONT_BOLD_ITALIC,
          potriveste(MENTIUNE, FONT_BOLD_ITALIC, 7.5, m[-1] - m[0] - 10), "centru")
    semnatar = f"Responsabil / Gestionar / Utilizator {responsabil}, {lista.titular}"
    _text(c, m[12], sus - 22, semnatar, FONT_BOLD_ITALIC, potriveste(semnatar, FONT_BOLD_ITALIC, 7.5, 420), "dreapta")
    c.line(m[9], jos + 6, m[12], jos + 6)
    return jos


def _latimi_semnaturi() -> list[float]:
    return [X0, X0 + 72, MARGINI[9] - 50, MARGINI[12] - 10, X1]


def _inaltime_semnaturi(lista: Lista) -> float:
    xs = _latimi_semnaturi()
    nume = imparte(", ".join(lista.comisie), FONT, 6.5, xs[2] - xs[1] - 6)
    return 11 + max(len(nume), 1) * 8 + 4 + 20


def _semnaturi(c: Canvas, sus: float, lista: Lista) -> None:
    _, responsabil = CATEGORII[lista.categorie]
    xs = _latimi_semnaturi()
    nume = imparte(", ".join(lista.comisie), FONT, 6.5, xs[2] - xs[1] - 6)
    h_nume = 11 + max(len(nume), 1) * 8 + 4
    jos_nume, jos = sus - h_nume, sus - h_nume - 20
    c.setLineWidth(0.8)
    c.rect(xs[0], jos, xs[-1] - xs[0], sus - jos)
    c.setLineWidth(0.3)
    for x in xs[1:-1]:
        c.line(x, jos, x, sus)
    c.line(xs[0], jos_nume, xs[-1], jos_nume)
    _text(c, (xs[0] + xs[1]) / 2, (sus + jos_nume) / 2 + 1, "Numele si", FONT, 6.5, "centru")
    _text(c, (xs[0] + xs[1]) / 2, (sus + jos_nume) / 2 - 7, "prenumele", FONT, 6.5, "centru")
    _text(c, (xs[0] + xs[1]) / 2, jos + 7, "Semnatura", FONT, 6.5, "centru")
    titluri = ("Comisia de inventariere", f"Responsabil / Gestionar / Utilizator {responsabil}", "C O N T A B I L I T A T E")
    for i, titlu in enumerate(titluri, start=1):
        _text(c, (xs[i] + xs[i + 1]) / 2, sus - 8, titlu, FONT, 6.5, "centru")
    for i, rand in enumerate(nume):
        _text(c, (xs[1] + xs[2]) / 2, sus - 18 - i * 8, rand, FONT, 6.5, "centru")
    _text(c, (xs[2] + xs[3]) / 2, sus - 18, lista.titular, FONT, potriveste(lista.titular, FONT, 6.5, xs[3] - xs[2] - 4),
          "centru")


def _subsol(c: Canvas, pagina: int, total: int) -> None:
    _text(c, X0, JOS - 10, f"Pagina {pagina} din {total}", FONT_ITALIC, 6)
    _text(c, X1, JOS - 10, "COD: 14-3-12", FONT_BOLD, 6, "dreapta")


def _deseneaza_lista(c: Canvas, lista: Lista, antet: Antet) -> None:
    limita = JOS + _inaltime_semnaturi(lista) + 4
    randuri = list(lista.randuri)
    pagina, nr = 1, 0
    while True:
        c.setLineWidth(0.3)
        y = _cap_tabel(c, _antet(c, lista, antet, pagina) - 3)
        pe_pagina = 0
        while randuri:
            inaltime = _masoara_rand(randuri[0])[1]
            if y - inaltime < limita:
                break
            # Totalul și mențiunea nu rămân singure pe o pagină: dacă nu încap după ultimul
            # rând, ultimul rând trece și el pe pagina următoare.
            if len(randuri) == 1 and pe_pagina and y - inaltime - INALTIME_FINAL < limita:
                break
            nr += 1
            pe_pagina += 1
            y = _rand(c, y, nr, randuri.pop(0), lista.categorie, antet.nivel_cont)
        gata = not randuri and y - INALTIME_FINAL >= limita
        if gata:
            y = _final(c, y, lista)
        _semnaturi(c, y - 4, lista)
        c.showPage()
        if gata:
            return
        pagina += 1


def deseneaza_liste(liste: list[Lista], antet: Antet) -> bytes:
    """Un singur PDF cu toate listele, în ordinea primită; subsolul numără pe tot fișierul."""
    inregistreaza_fonturi()
    continut = BytesIO()
    c = canvas_numerotat(_subsol)(continut, pagesize=(LATIME, INALTIME), pageCompression=1)
    c.setTitle(f"Liste de inventariere {data_ro(antet.data)}")
    c.setAuthor(antet.unitate)
    for lista in liste:
        _deseneaza_lista(c, lista, antet)
    c.save()
    return continut.getvalue()
