"""Sincronizarea anuală cu exportul contabil MF_BAZA (§9.4).

`analizeaza` compară exportul cu aplicația și propune acțiuni, fără să salveze nimic.
`incarca` salvează analiza (sincronizarea + diferențele) pentru revizuire.
`aplica` refă analiza pe același export, verifică faptul că propunerile alese nu s-au
schimbat între timp și le aplică pe toate într-o singură tranzacție.
"""
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.domain.documente import data_initiala, rezerva_scrierea, valideaza_fara_commit
from inventar.domain.neactualizare import marcheaza_neactualizate
from inventar.domain.normalizare import cont_sintetic
from inventar.domain.stoc import ORICAND, detinatori_la
from inventar.drepturi import Actor, cere_rol
from inventar.importuri.mf_baza import RandMF, RezultatCitire
from inventar.models import Bun, Cont, Document, LinieDocument, Persoana, Sincronizare, SincronizareDiferenta

TIPURI = {
    "BUN_NOU": "Bunuri noi în export (intră la nerepartizate; se repartizează apoi cu un document de intrare)",
    "CASARE": "Bunuri casate în contabilitate, încă active (se propune ieșirea, cu data și numărul casării)",
    "MODIFICAT": "Date schimbate în contabilitate (se actualizează, fără istoric)",
    "DISPARUT": "Bunuri dispărute din export, fără casare (doar semnalate, pentru verificare)",
    "ABSENT": "Bunuri active în aplicație, absente din contabilitate (doar semnalate)",
}
# Câmpurile bunului care vin din export (§7.1); toate se actualizează la sincronizare.
CAMPURI = ("nr_inventar_vechi", "categorie", "cont", "denumire", "um", "serie", "pret", "data_pif",
           "data_amortizare_integrala", "cod_clasificare", "durata_normala", "nr_doc_intrare", "data_doc_intrare",
           "nr_doc_casare", "data_casare", "explicatie_casare", "mentiuni")


@dataclass
class Diferenta:
    tip: str
    nr_inventar: str
    bun_id: int | None
    detalii: dict
    aplicabila: bool


@dataclass
class RandTotal:
    categorie: str
    cont: str
    export_numar: int = 0
    export_valoare: Decimal = Decimal("0")
    app_numar: int = 0
    app_valoare: Decimal = Decimal("0")


@dataclass
class Analiza:
    erori: list[str] = field(default_factory=list)
    diferente: list[Diferenta] = field(default_factory=list)
    totaluri: list[RandTotal] = field(default_factory=list)


def _text(valoare) -> str | None:
    return None if valoare is None else str(valoare)


def _valoare_bun(bun: Bun, camp: str):
    return bun.cont.simbol if camp == "cont" else getattr(bun, camp)


def _export(exporturi: list[RezultatCitire], analiza: Analiza) -> dict[str, RandMF]:
    rezultat: dict[str, RandMF] = {}
    for citire in exporturi:
        analiza.erori.extend(citire.erori)
        for r in citire.randuri:
            if r.nr_inventar in rezultat:
                analiza.erori.append(f"Nr. inventar {r.nr_inventar} apare de mai multe ori în export "
                                     f"({r.fisier}, rândul {r.rand}).")
            rezultat[r.nr_inventar] = r
    return rezultat


def analizeaza(session: Session, exporturi: list[RezultatCitire]) -> Analiza:
    analiza = Analiza()
    if data_initiala(session) is None:
        analiza.erori.append("Sincronizarea se face după importul inițial.")
    export = _export(exporturi, analiza)
    bunuri = {b.nr_inventar: b for b in session.scalars(select(Bun))}
    detinatori = detinatori_la(session, ORICAND, [b.id for b in bunuri.values()])
    nume = dict(session.execute(select(Persoana.id, Persoana.nume)).all())

    for nr, r in sorted(export.items()):
        bun = bunuri.get(nr)
        if bun is None:
            analiza.diferente.append(Diferenta("BUN_NOU", nr, None, {
                "denumire": r.denumire, "categorie": r.categorie, "cont": r.cont, "pret": str(r.pret),
                "data_doc_intrare": _text(r.data_doc_intrare), "casat": r.casat}, True))
            continue
        schimbari = {camp: [_text(_valoare_bun(bun, camp)), _text(getattr(r, camp))] for camp in CAMPURI
                     if _valoare_bun(bun, camp) != getattr(r, camp)}
        if schimbari:
            analiza.diferente.append(Diferenta("MODIFICAT", nr, bun.id, {"campuri": schimbari}, True))
        detinator = detinatori.get(bun.id)
        if r.casat and detinator is not None:
            analiza.diferente.append(Diferenta("CASARE", nr, bun.id, {
                "nr_doc_casare": r.nr_doc_casare, "data_casare": _text(r.data_casare),
                "explicatie": r.explicatie_casare, "detinator": nume.get(detinator), "detinator_id": detinator,
            }, r.data_casare is not None))

    for nr, bun in sorted(bunuri.items()):
        iesit = bun.id in detinatori and detinatori[bun.id] is None
        if nr in export or iesit:
            continue
        tip = "DISPARUT" if bun.prezent_in_export else "ABSENT"
        detinator = detinatori.get(bun.id)
        analiza.diferente.append(Diferenta(tip, nr, bun.id, {
            "denumire": bun.denumire, "detinator": nume.get(detinator) if detinator else None}, False))

    analiza.totaluri = _totaluri(export, bunuri, detinatori)
    return analiza


def _totaluri(export: dict[str, RandMF], bunuri: dict[str, Bun], detinatori: dict) -> list[RandTotal]:
    """Totaluri pe categorie și cont, în ambele surse: active în contabilitate (necasate) și în aplicație (neieșite)."""
    totaluri: dict[tuple, RandTotal] = {}
    for r in export.values():
        if not r.casat:
            t = totaluri.setdefault((r.categorie, r.cont), RandTotal(r.categorie, r.cont))
            t.export_numar += 1
            t.export_valoare += r.pret
    for b in bunuri.values():
        if not (b.id in detinatori and detinatori[b.id] is None):
            t = totaluri.setdefault((b.categorie, b.cont.simbol), RandTotal(b.categorie, b.cont.simbol))
            t.app_numar += 1
            t.app_valoare += b.pret
    return [totaluri[k] for k in sorted(totaluri)]


def _rezumat(analiza: Analiza) -> dict:
    return {
        "diferente": dict(Counter(d.tip for d in analiza.diferente)),
        "totaluri": [{"categorie": t.categorie, "cont": t.cont, "export_numar": t.export_numar,
                      "export_valoare": str(t.export_valoare), "app_numar": t.app_numar,
                      "app_valoare": str(t.app_valoare)} for t in analiza.totaluri],
    }


def incarca(session: Session, actor: Actor, exporturi: list[RezultatCitire], fisiere: list[dict],
            director: str) -> Sincronizare:
    cere_rol(actor, "OPERATOR")
    analiza = analizeaza(session, exporturi)
    if analiza.erori:
        raise EroareValidare(f"Exportul are {len(analiza.erori)} erori: " + " ".join(analiza.erori[:10]))
    sincronizare = Sincronizare(
        fisier=json.dumps(fisiere, ensure_ascii=False), director=director, incarcat_de=actor.utilizator_id,
        incarcat_la=datetime.now(), stare="INCARCATA", rezumat_json=json.dumps(_rezumat(analiza), ensure_ascii=False),
        diferente=[SincronizareDiferenta(tip=d.tip, nr_inventar=d.nr_inventar, bun_id=d.bun_id,
                                         detalii_json=json.dumps(d.detalii, ensure_ascii=False, sort_keys=True))
                   for d in analiza.diferente],
    )
    session.add(sincronizare)
    session.flush()
    jurnal.scrie(session, actor, "SINCRONIZARE_INCARCATA", "sincronizare", sincronizare.id,
                 {"fisiere": [f.get("original") for f in fisiere], **_rezumat(analiza)["diferente"]})
    session.commit()
    return sincronizare


def este_aplicabila(d: SincronizareDiferenta) -> bool:
    if d.tip == "CASARE":
        return json.loads(d.detalii_json).get("data_casare") is not None
    return d.tip in ("BUN_NOU", "MODIFICAT")


def _sincronizare_incarcata(session: Session, sincronizare_id: int) -> Sincronizare:
    sincronizare = session.get(Sincronizare, sincronizare_id)
    if sincronizare is None:
        raise EroareValidare("Sincronizarea nu există.")
    if sincronizare.stare != "INCARCATA":
        raise EroareValidare("Sincronizarea a fost deja aplicată sau abandonată.")
    return sincronizare


def _actualizeaza(session: Session, bun: Bun, r: RandMF, conturi: dict[str, Cont]) -> None:
    for camp in CAMPURI:
        if camp != "cont":
            setattr(bun, camp, getattr(r, camp))
    bun.cont = _cont(session, r, conturi)
    bun.actualizat_la = datetime.now()


def _cont(session: Session, r: RandMF, conturi: dict[str, Cont]) -> Cont:
    if r.cont not in conturi:
        conturi[r.cont] = Cont(simbol=r.cont, sintetic=cont_sintetic(r.cont), categorie=r.categorie)
        session.add(conturi[r.cont])
    return conturi[r.cont]


def _iesiri(session: Session, actor: Actor, casari: list[SincronizareDiferenta]) -> int:
    """Un document IESIRE validat pe fiecare casare (număr + dată), cu bunurile ei."""
    grupe: dict[tuple, list[SincronizareDiferenta]] = defaultdict(list)
    for d in casari:
        detalii = json.loads(d.detalii_json)
        grupe[(detalii["nr_doc_casare"] or "fără număr", detalii["data_casare"])].append(d)
    for (numar, data_text), diferente in sorted(grupe.items(), key=lambda x: (x[0][1], x[0][0])):
        data = date.fromisoformat(data_text)
        explicatie = json.loads(diferente[0].detalii_json).get("explicatie")
        document = Document(tip="IESIRE", numar=numar, data=data, motiv_iesire="CASARE", stare="CIORNA",
                            explicatie=f"Casare din contabilitate{': ' + explicatie if explicatie else ''}",
                            creat_de=actor.utilizator_id, creat_la=datetime.now())
        session.add(document)
        session.flush()
        detinatori = detinatori_la(session, data, [d.bun_id for d in diferente])
        for d in diferente:
            session.add(LinieDocument(document_id=document.id, bun_id=d.bun_id,
                                      persoana_de_la_id=detinatori.get(d.bun_id) or
                                      json.loads(d.detalii_json)["detinator_id"]))
        session.flush()
        session.refresh(document)
        valideaza_fara_commit(session, actor, document)
    return len(grupe)


def aplica(session: Session, actor: Actor, sincronizare_id: int, exporturi: list[RezultatCitire],
           selectate: set[int]) -> dict:
    cere_rol(actor, "OPERATOR")
    rezerva_scrierea(session)
    sincronizare = _sincronizare_incarcata(session, sincronizare_id)
    try:
        analiza = analizeaza(session, exporturi)
        if analiza.erori:
            raise EroareValidare("Exportul nu mai poate fi citit fără erori.")
        proaspete = {(d.tip, d.nr_inventar): json.dumps(d.detalii, ensure_ascii=False, sort_keys=True)
                     for d in analiza.diferente}
        alese = [d for d in sincronizare.diferente if d.id in selectate and este_aplicabila(d)]
        for d in alese:
            if proaspete.get((d.tip, d.nr_inventar)) != d.detalii_json:
                raise EroareValidare(f"Situația s-a schimbat de la încărcare (bunul {d.nr_inventar}); "
                                     "abandonați această sincronizare și încărcați din nou exportul.")

        export = {r.nr_inventar: r for c in exporturi for r in c.randuri}
        bunuri = {b.nr_inventar: b for b in session.scalars(select(Bun))}
        conturi = {c.simbol: c for c in session.scalars(select(Cont))}
        acum = datetime.now()
        for d in alese:
            r = export[d.nr_inventar]
            if d.tip == "MODIFICAT":
                _actualizeaza(session, bunuri[d.nr_inventar], r, conturi)
            elif d.tip == "BUN_NOU":
                bun = Bun(nr_inventar=r.nr_inventar, prezent_in_export=True, actualizat_la=acum)
                _actualizeaza(session, bun, r, conturi)
                session.add(bun)
        # Prezența în export e un fapt al contabilității: se actualizează la orice sincronizare aplicată.
        prezenta = 0
        for nr, bun in bunuri.items():
            if bun.prezent_in_export != (nr in export):
                bun.prezent_in_export = nr in export
                prezenta += 1
        session.flush()

        documente_iesire = _iesiri(session, actor, [d for d in alese if d.tip == "CASARE"])
        if any(d.tip in ("MODIFICAT", "BUN_NOU") for d in alese) or prezenta:
            # Datele bunurilor apar în toate instantaneele, indiferent de dată.
            marcheaza_neactualizate(session, actor, date.min, f"sincronizarea nr. {sincronizare.id}")

        for d in sincronizare.diferente:
            if d in alese:
                d.actiune, d.rezolvat = "APLICAT", True
            else:
                d.actiune = "IGNORAT" if este_aplicabila(d) else "SEMNALAT"
        sincronizare.stare, sincronizare.aplicat_la = "APLICATA", acum
        aplicate = dict(Counter(d.tip for d in alese))
        jurnal.scrie(session, actor, "SINCRONIZARE_APLICATA", "sincronizare", sincronizare.id, {
            "aplicate": aplicate, "ignorate": sum(d.actiune == "IGNORAT" for d in sincronizare.diferente),
            "prezenta_schimbata": prezenta, "documente_iesire": documente_iesire,
        })
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"aplicate": aplicate, "documente_iesire": documente_iesire, "prezenta_schimbata": prezenta}


def abandoneaza(session: Session, actor: Actor, sincronizare_id: int) -> None:
    cere_rol(actor, "OPERATOR")
    sincronizare = _sincronizare_incarcata(session, sincronizare_id)
    sincronizare.stare = "ABANDONATA"
    jurnal.scrie(session, actor, "SINCRONIZARE_ABANDONATA", "sincronizare", sincronizare.id)
    session.commit()


ETICHETE_CAMPURI = {
    "nr_inventar_vechi": "nr. inventar vechi", "categorie": "categorie", "cont": "cont", "denumire": "denumire",
    "um": "U/M", "serie": "serie", "pret": "valoare", "data_pif": "data PIF",
    "data_amortizare_integrala": "data amortizării integrale", "cod_clasificare": "cod clasificare",
    "durata_normala": "durată normală", "nr_doc_intrare": "nr. doc. intrare", "data_doc_intrare": "data doc. intrare",
    "nr_doc_casare": "nr. doc. casare", "data_casare": "data casării", "explicatie_casare": "explicație casare",
    "mentiuni": "mențiuni",
}


def _afisare(valoare: str | None) -> str:
    """Datele se salvează ISO în detalii; pe ecran și în raport apar ca dd.mm.yyyy."""
    if valoare and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valoare):
        return date.fromisoformat(valoare).strftime("%d.%m.%Y")
    return valoare or "—"


def descriere_diferenta(d: SincronizareDiferenta) -> str:
    """Textul unei diferențe, pentru ecran și pentru raportul exportat."""
    x = json.loads(d.detalii_json)
    if d.tip == "BUN_NOU":
        text = f"{x['denumire']} — {x['categorie']}, cont {x['cont']}, valoare {x['pret']}"
        return text + (f", document de intrare din {_afisare(x['data_doc_intrare'])}" if x.get("data_doc_intrare") else "")
    if d.tip == "CASARE":
        if not x.get("data_casare"):
            return (f"casat ({x.get('nr_doc_casare') or 'fără număr'}) fără dată de casare; la {x['detinator']} — "
                    "ieșirea se face manual")
        return f"casare nr. {x.get('nr_doc_casare') or '—'} din {_afisare(x['data_casare'])}; acum la {x['detinator']}"
    if d.tip == "MODIFICAT":
        return "; ".join(f"{ETICHETE_CAMPURI.get(c, c)}: {_afisare(v[0])} → {_afisare(v[1])}"
                         for c, v in x["campuri"].items())
    return f"{x['denumire']}" + (f" — la {x['detinator']}" if x.get("detinator") else " — nerepartizat")
