"""Centralizatoare și export din instantaneu, ca fișiere (PDF, Excel, CSV), cu urmă în jurnal."""
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.centralizatoare import TIPURI, centralizator
from inventar.domain.comun import EroareValidare
from inventar.domain.filtre import descriere
from inventar.domain.generare import Perimetru
from inventar.domain.setari import citeste_setari
from inventar.drepturi import Actor, cere_rol
from inventar.export.excel import centralizator_xlsx, linii_csv, linii_xlsx, tabele_xlsx
from inventar.importuri.sincronizare import descriere_diferenta
from inventar.models import Sincronizare
from inventar.pdf.centralizatoare import deseneaza_centralizator, deseneaza_tabele
from inventar.pdf.comun import nume_fisier
from inventar.tiparire import inventar_actual, linii_filtrate

TIPURI_MIME = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}


def _nume(prefix: str, data: str, format_: str) -> str:
    return nume_fisier(prefix, data)[:-4] + f".{format_}"


def centralizator_fisier(session: Session, actor: Actor, inventar_id: int, tip: str, format_: str,
                         filtru: Perimetru = Perimetru()) -> tuple[str, bytes, str]:
    cere_rol(actor, "CONSULTARE")
    if tip not in TIPURI or format_ not in ("pdf", "xlsx"):
        raise EroareValidare("Centralizator sau format necunoscut.")
    inventar = inventar_actual(session, inventar_id)
    randuri = centralizator(session, inventar.id, tip, filtru)
    titlu = f"Centralizator {TIPURI[tip][0]}"
    text_filtru = descriere(session, filtru)
    if format_ == "pdf":
        continut = deseneaza_centralizator(randuri, citeste_setari(session)["unitate"], titlu, inventar.data,
                                           text_filtru)
    else:
        continut = centralizator_xlsx(randuri, f"{titlu} — inventarul la {inventar.data:%d.%m.%Y}",
                                      f"Filtru: {text_filtru}")
    nume = _nume(f"Centralizator_{tip}", inventar.data.isoformat(), format_)
    jurnal.scrie(session, actor, "CENTRALIZATOR", "inventar", inventar.id,
                 {"fisier": nume, "tip": tip, "filtru": json.loads(filtru.json())})
    session.commit()
    return nume, continut, TIPURI_MIME[format_]


def export_linii(session: Session, actor: Actor, inventar_id: int, format_: str,
                 filtru: Perimetru = Perimetru()) -> tuple[str, bytes, str]:
    """Situație ad-hoc: un rând pe bun, toate câmpurile din instantaneu."""
    cere_rol(actor, "CONSULTARE")
    if format_ not in ("xlsx", "csv"):
        raise EroareValidare("Formatul exportului poate fi xlsx sau csv.")
    inventar = inventar_actual(session, inventar_id)
    linii = linii_filtrate(session, inventar, filtru)
    if format_ == "xlsx":
        continut = linii_xlsx(linii, f"Inventarul la {inventar.data:%d.%m.%Y}")
    else:
        continut = linii_csv(linii)
    nume = _nume("Export_inventar", inventar.data.isoformat(), format_)
    jurnal.scrie(session, actor, "EXPORT", "inventar", inventar.id,
                 {"fisier": nume, "linii": len(linii), "filtru": json.loads(filtru.json())})
    session.commit()
    return nume, continut, TIPURI_MIME[format_]


def raport_sincronizare(session: Session, actor: Actor, sincronizare_id: int, format_: str) -> tuple[str, bytes, str]:
    """Raportul unei sincronizări: totaluri pe categorie și cont în ambele surse, plus diferențele."""
    cere_rol(actor, "CONSULTARE")
    if format_ not in ("pdf", "xlsx"):
        raise EroareValidare("Formatul raportului poate fi pdf sau xlsx.")
    sincronizare = session.get(Sincronizare, sincronizare_id)
    if sincronizare is None:
        raise EroareValidare("Sincronizarea nu există.")
    totaluri = json.loads(sincronizare.rezumat_json).get("totaluri", [])
    antet_totaluri = ["Categorie", "Cont", "Contabilitate: nr.", "Contabilitate: valoare", "Aplicație: nr.",
                      "Aplicație: valoare", "Diferență valoare"]
    randuri_totaluri = [[t["categorie"], t["cont"], t["export_numar"], Decimal(t["export_valoare"]), t["app_numar"],
                         Decimal(t["app_valoare"]), Decimal(t["export_valoare"]) - Decimal(t["app_valoare"])]
                        for t in totaluri]
    antet_diferente = ["Tip", "Nr. inventar", "Detalii", "Acțiune"]
    randuri_diferente = [[d.tip, d.nr_inventar, descriere_diferenta(d), d.actiune or ""] for d in sincronizare.diferente]
    titlu = f"Sincronizarea nr. {sincronizare.id} din {sincronizare.incarcat_la:%d.%m.%Y %H:%M}"
    if format_ == "xlsx":
        continut = tabele_xlsx([("Totaluri", antet_totaluri, randuri_totaluri),
                                ("Diferențe", antet_diferente, randuri_diferente)], titlu)
    else:
        continut = deseneaza_tabele(citeste_setari(session)["unitate"], titlu,
                                    [("Totaluri pe categorie și cont", antet_totaluri, randuri_totaluri),
                                     ("Diferențe", antet_diferente, randuri_diferente)])
    nume = f"Sincronizare_{sincronizare.id}_{sincronizare.incarcat_la:%Y-%m-%d}.{format_}"
    jurnal.scrie(session, actor, "RAPORT_SINCRONIZARE", "sincronizare", sincronizare.id, {"fisier": nume})
    session.commit()
    return nume, continut, TIPURI_MIME[format_]
