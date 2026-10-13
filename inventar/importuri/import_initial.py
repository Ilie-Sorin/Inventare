"""Importul inițial (§9.3): exportul contabil + extrasul din aplicația existentă.

`analizeaza` nu salvează nimic: construiește planul și raportul. `confirma` refă
analiza (cu deciziile operatorului) și, dacă nu sunt erori, salvează totul într-o
singură tranzacție, împreună cu documentul INITIAL validat.
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inventar import jurnal
from inventar.domain.comun import EroareValidare
from inventar.domain.normalizare import cheie_nume, cont_sintetic
from inventar.drepturi import Actor, cere_rol
from inventar.importuri.extras import RandExtras
from inventar.importuri.mf_baza import RandMF, RezultatCitire
from inventar.models import Activitate, Bun, Cont, Document, Incadrare, LinieDocument, Locatie, Persoana

PRAG_SIMILARITATE = 0.85

# Deciziile posibile pentru o pereche de nume apropiate (A < B alfabetic).
DECIZII = {
    "DIFERITE": "Persoane diferite",
    "UNIFICA_A": "Aceeași persoană — se păstrează numele A",
    "UNIFICA_B": "Aceeași persoană — se păstrează numele B",
    "B_SECUNDARA_A": "B este gestiune secundară a lui A",
    "A_SECUNDARA_B": "A este gestiune secundară a lui B",
}

AV_FARA_PERSOANA = "Bunuri din export fără persoană în extras (rămân nerepartizate)"
AV_NR_VECHI = "Număr de inventar vechi diferit (se păstrează valoarea din export)"
AV_CASATE = "Bunuri casate în contabilitate, dar repartizate în extras"
AV_CONT = "Conturi care apar la ambele categorii"


@dataclass(frozen=True)
class PerecheSimilara:
    a: str
    b: str
    similaritate: float

    @property
    def cheie(self) -> str:
        return hashlib.sha1(f"{self.a}\x00{self.b}".encode()).hexdigest()[:12]


@dataclass
class PersoanaPlan:
    nume: str
    locatie: str
    activitate: str
    titular: str | None = None
    nume_extras: set[str] = field(default_factory=set)


@dataclass
class Raport:
    erori: list[str] = field(default_factory=list)
    avertismente: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    perechi: list[PerecheSimilara] = field(default_factory=list)
    nedecise: list[PerecheSimilara] = field(default_factory=list)
    persoane: dict[str, PersoanaPlan] = field(default_factory=dict)
    bunuri: list[RandMF] = field(default_factory=list)
    repartizari: dict[str, str] = field(default_factory=dict)  # nr_inventar → nume persoană finală
    statistici: dict[str, object] = field(default_factory=dict)

    @property
    def poate_confirma(self) -> bool:
        return not self.erori and not self.nedecise


def perechi_similare(nume: list[str]) -> list[PerecheSimilara]:
    """Nume foarte apropiate: identice fără diacritice/majuscule, unul prefix al celuilalt
    („AIONITOAIE CORNELIU” / „AIONITOAIE CORNELIU VIRGIL et II”) sau similaritate difflib ≥ prag."""
    chei = sorted((n, cheie_nume(n)) for n in set(nume))
    rezultat = []
    for i, (a, ka) in enumerate(chei):
        for b, kb in chei[i + 1:]:
            potrivire = SequenceMatcher(None, ka, kb, autojunk=False)
            prefix = ka == kb or kb.startswith(ka + " ") or ka.startswith(kb + " ")
            if prefix or (potrivire.real_quick_ratio() >= PRAG_SIMILARITATE
                          and potrivire.quick_ratio() >= PRAG_SIMILARITATE
                          and potrivire.ratio() >= PRAG_SIMILARITATE):
                rezultat.append(PerecheSimilara(a, b, round(potrivire.ratio(), 2)))
    return rezultat


def _verifica_baza_goala(session: Session, raport: Raport) -> None:
    if session.scalar(select(func.count()).select_from(Document).where(Document.tip == "INITIAL")):
        raport.erori.append("Importul inițial a fost deja făcut.")
    if session.scalar(select(func.count()).select_from(Bun)):
        raport.erori.append("Există deja bunuri în aplicație; importul inițial se face pe o bază fără bunuri.")
    numar_persoane = session.scalar(select(func.count()).select_from(Persoana))
    if numar_persoane:
        raport.erori.append(
            f"Există deja {numar_persoane} persoane în aplicație; importul inițial le creează din extras, "
            "deci se face pe o bază fără persoane."
        )


def _analizeaza_export(randuri: list[RandMF], raport: Raport) -> dict[str, RandMF]:
    dupa_nr: dict[str, RandMF] = {}
    categorii_cont: dict[str, set[str]] = defaultdict(set)
    for r in randuri:
        if r.nr_inventar in dupa_nr:
            primul = dupa_nr[r.nr_inventar]
            raport.erori.append(
                f"Nr. inventar {r.nr_inventar} apare de mai multe ori în export "
                f"({primul.fisier} rândul {primul.rand}; {r.fisier} rândul {r.rand})."
            )
            continue
        dupa_nr[r.nr_inventar] = r
        categorii_cont[r.cont].add(r.categorie)
    for cont, categorii in sorted(categorii_cont.items()):
        if len(categorii) > 1:
            raport.avertismente[AV_CONT].append(f"Contul {cont} apare și la MF, și la OI.")
    raport.bunuri = list(dupa_nr.values())
    return dupa_nr


def _analizeaza_extras(extras: list[RandExtras], export: dict[str, RandMF], raport: Raport) -> list[RandExtras]:
    valide, vazute = [], {}
    for r in extras:
        if r.nr_inventar in vazute:
            raport.erori.append(
                f"Nr. inventar {r.nr_inventar} apare de mai multe ori în extras (rândurile {vazute[r.nr_inventar]} "
                f"și {r.rand})."
            )
            continue
        vazute[r.nr_inventar] = r.rand
        bun = export.get(r.nr_inventar)
        if bun is None:
            raport.erori.append(f"Extras, rândul {r.rand}: nr. inventar {r.nr_inventar} nu există în export.")
            continue
        if bun.categorie != r.categorie:
            raport.erori.append(
                f"Extras, rândul {r.rand}: nr. inventar {r.nr_inventar} este {r.categorie} în extras, "
                f"dar {bun.categorie} în export."
            )
            continue
        if r.nr_inventar_vechi != bun.nr_inventar_vechi:
            raport.avertismente[AV_NR_VECHI].append(
                f"{r.nr_inventar}: extras „{r.nr_inventar_vechi or '—'}”, export „{bun.nr_inventar_vechi or '—'}”."
            )
        if bun.casat:
            data = f"{bun.data_casare:%d.%m.%Y}" if bun.data_casare else "fără dată"
            raport.avertismente[AV_CASATE].append(
                f"{r.nr_inventar} ({bun.denumire}) — casat ({bun.nr_doc_casare or 'fără număr'}, {data}), "
                f"la {r.persoana}. Ieșirea se propune la sincronizare."
            )
        valide.append(r)
    for nr, bun in sorted(export.items()):
        if nr not in vazute and not bun.casat:
            raport.avertismente[AV_FARA_PERSOANA].append(f"{nr} — {bun.denumire} ({bun.categorie}, {bun.cont}).")
    return valide


def _aplica_decizii(perechi: list[PerecheSimilara], decizii: dict[str, str],
                    raport: Raport) -> tuple[dict[str, str], dict[str, str]]:
    """Întoarce (redenumiri: nume → nume păstrat, titulari: gestiune secundară → titular)."""
    redenumiri: dict[str, str] = {}
    titulari: dict[str, str] = {}
    for p in perechi:
        decizie = decizii.get(p.cheie)
        if decizie not in DECIZII:
            raport.nedecise.append(p)
        elif decizie == "DIFERITE" and p.a.casefold() == p.b.casefold():
            raport.erori.append(f"„{p.a}” și „{p.b}” diferă doar prin majuscule; nu pot fi gestiuni diferite.")
        elif decizie == "UNIFICA_A":
            redenumiri[p.b] = p.a
        elif decizie == "UNIFICA_B":
            redenumiri[p.a] = p.b
        elif decizie == "B_SECUNDARA_A":
            titulari[p.b] = p.a
        elif decizie == "A_SECUNDARA_B":
            titulari[p.a] = p.b

    def final(nume: str) -> str:
        vazute = set()
        while nume in redenumiri and nume not in vazute:
            vazute.add(nume)
            nume = redenumiri[nume]
        return nume

    redenumiri_finale = {n: final(n) for n in redenumiri}
    titulari_finali: dict[str, str] = {}
    for secundara, titular in titulari.items():
        s, t = final(secundara), final(titular)
        if s == t:
            raport.erori.append(f"„{secundara}” nu poate fi gestiune secundară a propriei persoane „{titular}”.")
        elif s in titulari_finali and titulari_finali[s] != t:
            raport.erori.append(f"„{s}” are doi titulari aleși: „{titulari_finali[s]}” și „{t}”.")
        else:
            titulari_finali[s] = t
    for s, t in titulari_finali.items():
        if t in titulari_finali:
            raport.erori.append(f"„{t}” este titular pentru „{s}”, dar este la rândul lui gestiune secundară.")
    return redenumiri_finale, titulari_finali


def _construieste_persoane(extras: list[RandExtras], valide: list[RandExtras], redenumiri: dict[str, str],
                           titulari: dict[str, str], raport: Raport) -> None:
    # Persoanele și încadrările se verifică pe toate rândurile, ca operatorul să vadă
    # toate problemele dintr-o trecere; repartizările se fac doar din rândurile valide.
    incadrari: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for r in extras:
        nume = redenumiri.get(r.persoana, r.persoana)
        incadrari[nume].add((r.locatie, r.activitate))
        plan = raport.persoane.setdefault(nume, PersoanaPlan(nume, r.locatie, r.activitate))
        plan.nume_extras.add(r.persoana)
    for r in valide:
        raport.repartizari[r.nr_inventar] = redenumiri.get(r.persoana, r.persoana)
    for nume, variante in sorted(incadrari.items()):
        if len(variante) > 1:
            lista = "; ".join(f"{loc} / {act}" for loc, act in sorted(variante))
            raport.erori.append(f"Persoana „{nume}” apare cu locații sau activități diferite: {lista}.")
    for secundara, titular in titulari.items():
        if secundara in raport.persoane:
            raport.persoane[secundara].titular = titular


def _verifica_nomenclatoare(session: Session, raport: Raport) -> None:
    for model, nume_tip, valori in (
        (Locatie, "Locația", {p.locatie for p in raport.persoane.values()}),
        (Activitate, "Activitatea", {p.activitate for p in raport.persoane.values()}),
    ):
        existente = {o.cod.casefold(): o for o in session.scalars(select(model))}
        for valoare in sorted(valori):
            obiect = existente.get(valoare.casefold())
            if obiect is not None and not obiect.activ:
                raport.erori.append(f"{nume_tip} „{valoare}” există în aplicație, dar este inactivă.")


def _statistici(raport: Raport) -> None:
    total: dict[str, list] = defaultdict(lambda: [0, Decimal("0"), 0, Decimal("0")])
    for b in raport.bunuri:
        t = total[b.categorie]
        t[0] += 1
        t[1] += b.pret
        if b.nr_inventar in raport.repartizari:
            t[2] += 1
            t[3] += b.pret
    raport.statistici = {
        "categorii": {c: {"bunuri": v[0], "valoare": v[1], "repartizate": v[2], "valoare_repartizata": v[3]}
                      for c, v in sorted(total.items())},
        "persoane": len(raport.persoane),
        "gestiuni_secundare": sum(1 for p in raport.persoane.values() if p.titular),
        "locatii": len({p.locatie for p in raport.persoane.values()}),
        "activitati": len({p.activitate for p in raport.persoane.values()}),
    }


def analizeaza(session: Session, exporturi: list[RezultatCitire], extras: RezultatCitire,
               data_start: date | None, decizii: dict[str, str] | None = None) -> Raport:
    raport = Raport()
    for citire in [*exporturi, extras]:
        raport.erori.extend(citire.erori)
    if data_start is None:
        raport.erori.append("Data de start este obligatorie.")
    _verifica_baza_goala(session, raport)

    export = _analizeaza_export([r for c in exporturi for r in c.randuri], raport)
    extras_valid = _analizeaza_extras(extras.randuri, export, raport)
    raport.perechi = perechi_similare([r.persoana for r in extras.randuri])
    redenumiri, titulari = _aplica_decizii(raport.perechi, decizii or {}, raport)
    _construieste_persoane(extras.randuri, extras_valid, redenumiri, titulari, raport)
    _verifica_nomenclatoare(session, raport)
    _statistici(raport)
    return raport


def _obtine(session: Session, model, cache: dict[str, object], valoare: str):
    cheie = valoare.casefold()
    if cheie not in cache:
        obiect = model(cod=valoare, denumire=valoare, activ=True)
        session.add(obiect)
        cache[cheie] = obiect
    return cache[cheie]


def confirma(session: Session, actor: Actor, exporturi: list[RezultatCitire], extras: RezultatCitire,
             data_start: date, decizii: dict[str, str], fisiere: list[str]) -> Document:
    cere_rol(actor, "OPERATOR")
    raport = analizeaza(session, exporturi, extras, data_start, decizii)
    if raport.erori:
        raise EroareValidare(f"Importul nu poate fi confirmat: există {len(raport.erori)} erori blocante.")
    if raport.nedecise:
        raise EroareValidare(f"Alegeți o variantă pentru toate cele {len(raport.nedecise)} perechi de nume apropiate.")
    acum = datetime.now()
    try:
        locatii = {o.cod.casefold(): o for o in session.scalars(select(Locatie))}
        activitati = {o.cod.casefold(): o for o in session.scalars(select(Activitate))}
        conturi = {c.simbol: c for c in session.scalars(select(Cont))}
        bunuri: dict[str, Bun] = {}
        for r in raport.bunuri:
            if r.cont not in conturi:
                conturi[r.cont] = Cont(simbol=r.cont, sintetic=cont_sintetic(r.cont), categorie=r.categorie)
                session.add(conturi[r.cont])
            bun = Bun(
                nr_inventar=r.nr_inventar, nr_inventar_vechi=r.nr_inventar_vechi, categorie=r.categorie,
                cont=conturi[r.cont], denumire=r.denumire, um=r.um, serie=r.serie, pret=r.pret,
                data_pif=r.data_pif, data_amortizare_integrala=r.data_amortizare_integrala,
                cod_clasificare=r.cod_clasificare, durata_normala=r.durata_normala,
                nr_doc_intrare=r.nr_doc_intrare, data_doc_intrare=r.data_doc_intrare,
                nr_doc_casare=r.nr_doc_casare, data_casare=r.data_casare, explicatie_casare=r.explicatie_casare,
                mentiuni=r.mentiuni, prezent_in_export=True, actualizat_la=acum,
            )
            session.add(bun)
            bunuri[r.nr_inventar] = bun

        persoane: dict[str, Persoana] = {}
        # Titularii întâi, ca gestiunile secundare să-i poată referi.
        for plan in sorted(raport.persoane.values(), key=lambda p: (p.titular is not None, p.nume)):
            persoana = Persoana(nume=plan.nume, activ=True,
                                titular=persoane[plan.titular] if plan.titular else None)
            session.add(persoana)
            session.add(Incadrare(
                persoana=persoana, locatie=_obtine(session, Locatie, locatii, plan.locatie),
                activitate=_obtine(session, Activitate, activitati, plan.activitate),
                valabil_de_la=data_start, motiv="import inițial",
            ))
            persoane[plan.nume] = persoana

        document = Document(
            tip="INITIAL", numar="1", data=data_start, stare="VALIDAT",
            explicatie="Import inițial: " + ", ".join(fisiere),
            creat_de=actor.utilizator_id, creat_la=acum, validat_de=actor.utilizator_id, validat_la=acum,
        )
        session.add(document)
        for nr, nume in raport.repartizari.items():
            session.add(LinieDocument(document=document, bun=bunuri[nr], persoana_la=persoane[nume]))
        session.flush()

        jurnal.scrie(session, actor, "IMPORT_INITIAL", "document", document.id, {
            "fisiere": fisiere, "data_start": data_start, "bunuri": len(bunuri),
            "repartizate": len(raport.repartizari), "persoane": len(persoane),
            "decizii_nume": {f"{p.a} | {p.b}": decizii[p.cheie] for p in raport.perechi},
        })
        session.commit()
    except Exception:
        session.rollback()
        raise
    return document
