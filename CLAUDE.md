# Aplicație liste de inventariere — instrucțiuni pentru Claude Code

Aplicație web internă care ține evidența bunurilor (mijloace fixe și obiecte de inventar) **pe gestiuni / persoane, locații și activități** și generează, la orice dată, **listele de inventariere conform legislației** (formular 14-3-12, OMFP 2861/2009), cu declarații, centralizatoare, PDF, e-mail și export.

**Evidența contabilă NU se ține aici.** Ea rămâne în sistemul contabil existent. Aplicația importă de acolo datele bunurilor (export `MF_BAZA`) și ține doar ce lipsește în contabilitate: la cine, în ce locație și în ce activitate se află fiecare bun.

Principiul care primează la orice decizie: **fără complicații inutile.** Când o variantă mai simplă acoperă nevoia, se alege aceea. Dacă o cerință pare să ceară ceva complicat, întreabă înainte să implementezi.

---

## 1. Mediu și constrângeri

- Server intern **Windows**. Utilizatorii lucrează din browser, din mai multe locații, în rețeaua internă.
- **Fără WinRM, fără GPO, fără Docker.** Nimic nu se instalează pe stațiile utilizatorilor.
- **Fără acces la internet la rulare.** Nu se folosesc CDN-uri: Bootstrap, htmx și fonturile sunt servite local din `static/`.
- Utilizatori: 2–3 operatori și un administrator, care pot lucra simultan.
- Volum: un tiraj de inventar are ~250–300 de pagini, cu câteva mii de bunuri.
- Interfața este în **limba română, cu diacritice corecte** (ș, ț cu virgulă dedesubt).

## 2. Stack (decis — nu schimba fără acord)

| Componentă | Alegere |
| --- | --- |
| Limbaj | Python 3.12 |
| Web | Flask, Jinja2, htmx (local), Bootstrap 5 (local) |
| ORM / migrări | SQLAlchemy 2 (stil 2.0, `Mapped[...]`), Flask-SQLAlchemy, Flask-Migrate (Alembic) |
| Bază de date | SQLite, `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON` |
| Autentificare | Flask-Login; parole cu `werkzeug.security` |
| Formulare | Flask-WTF (CSRF activ peste tot) |
| PDF | ReportLab, cu font TTF pentru diacritice (DejaVu Sans, inclus în `inventar/pdf/fonts/`) |
| Excel | `xlrd` pentru `.xls` (MF_BAZA), `openpyxl` pentru `.xlsx` (extras, export) |
| E-mail | `smtplib` (stdlib), SMTP-ul instituției |
| Criptare parolă SMTP | `cryptography` (Fernet), cheie în `instance/secret.key` |
| Server | Waitress, rulat ca serviciu Windows prin NSSM; HTTPS prin IIS sau Caddy ca reverse proxy |
| Teste | pytest |

**Nu adăuga alte dependențe fără să întrebi.** Nu folosi Celery, Redis, React/Vue, Docker, WeasyPrint sau pandas.

## 3. Comenzi

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

flask --app inventar db upgrade            # aplică migrările
flask --app inventar creeaza-admin         # primul utilizator administrator
flask --app inventar run --debug           # dezvoltare, http://127.0.0.1:5000

pytest                                     # toate testele
pytest tests/domain -q                     # doar logica de domeniu

waitress-serve --listen=127.0.0.1:8080 inventar.wsgi:app   # producție (în spatele IIS/Caddy)
python scripts/backup.py                   # backup SQLite (API online), rulat zilnic din Task Scheduler
```

`requirements.txt` conține versiuni fixate (`==`).

## 4. Structura proiectului

```
inventar/
  __init__.py          create_app()
  config.py            configurare (din instance/config.py + variabile de mediu)
  extensions.py        db, migrate, login_manager, csrf
  wsgi.py              app pentru Waitress
  cli.py               comenzi flask (creeaza-admin etc.)
  models/              modele SQLAlchemy, un modul pe zonă
  domain/              LOGICA DE DOMENIU — Python pur, fără Flask
    stoc.py            situația la o dată (cine are ce)
    documente.py       validare, anulare, reguli cronologice
    incadrare.py       încadrarea valabilă la o dată
    generare.py        generare / ștergere / regenerare / blocare inventar
    normalizare.py     conturi, date, numere de inventar, nume
  importuri/
    mf_baza.py         citire export contabil (.xls)
    extras.py          citire extras din aplicația existentă (.xlsx)
    import_initial.py  import inițial: validare, raport, confirmare
    sincronizare.py    sincronizarea anuală cu exportul contabil
  pdf/
    lista.py           lista de inventariere 14-3-12
    declaratii.py      declarația de început și cea de sfârșit
    centralizatoare.py
    comun.py           fonturi, formatare numere/date, canvas cu „Pagina X din Y”
    fonts/
  email/trimitere.py
  export/excel.py
  jurnal.py            scrie în jurnalul de acțiuni (append-only)
  web/                 blueprints: auth, nomenclatoare, persoane, documente,
                       inventare, rapoarte, importuri, admin
  templates/
  static/              bootstrap, htmx, css, sigla
migrations/
scripts/               backup.py, instalare_serviciu.ps1
tests/
  domain/  importuri/  pdf/  web/
docs/
  exemple/             fișierele reale primite (vezi §12)
```

**Regula de bază a arhitecturii:** tot ce e logică de domeniu stă în `domain/` și `importuri/` și primește o sesiune SQLAlchemy ca parametru. Nu importă `flask`. Rutele din `web/` doar citesc formularul, apelează serviciul și afișează rezultatul.

## 5. Convenții de cod

- Identificatorii de domeniu sunt **în română, fără diacritice**: `bun`, `persoana`, `incadrare`, `document`, `linie_document`, `inventar`, `gestiune`, `titular`, `comisie`. Cei tehnici sunt în engleză (`create_app`, `session`, `config`).
- Textele din interfață, mesajele de eroare și PDF-urile sunt în română, **cu diacritice**.
- **Bani: `Decimal`, niciodată `float`.** În baza de date se folosește `Numeric(15, 2)`. Valorile citite cu xlrd (float) se convertesc cu `Decimal(str(round(x, 2)))`.
- Datele se stochează ca `date` (ISO) și se afișează `dd.mm.yyyy`.
- Formatul numerelor afișate: virgulă zecimală. **Pe liste fără separator de mii** (`4034,10`, `11658,74`, ca în exemple); în ecrane se poate folosi `4.034,10`.
- **Nicio ștergere fizică** pentru înregistrările folosite în documente: se folosește `activ = False`.
- **Orice acțiune care schimbă date** (inclusiv generarea de PDF, trimiterea de e-mail și exportul) trece printr-o funcție de serviciu. Aceasta scrie în `jurnal`, în **aceeași tranzacție**.
- Operațiile compuse (validare document, generare inventar, import, sincronizare) sunt **atomice**: reușesc complet sau deloc.
- Type hints peste tot; funcții mici; fără clase acolo unde ajunge o funcție.
- Nu introduce abstracții „pentru viitor” (repository pattern, plugin-uri, event bus).

## 6. Glosar de domeniu

| Termen | Sens |
| --- | --- |
| Bun | Un obiect cu număr de inventar unic: **MF** (mijloc fix) sau **OI** (obiect de inventar). Cantitatea este mereu 1. |
| Categorie | `MF` sau `OI`. Vine din `mf_oi` (`M` / `O`) din export. |
| Cont | Contul analitic al bunului (ex. `303.02.00.04`). Contul sintetic = primele 3 cifre (`303`). |
| Persoană / gestiune | Cel care are bunuri în primire. **O înregistrare din `persoana` = o gestiune = o listă.** |
| Titular | Câmp opțional al unei gestiuni secundare, care trimite la persoana fizică (vezi §7.3). |
| Încadrare | Locația și activitatea unei persoane, valabile de la o dată. Se păstrează istoricul. |
| Locație | Sediul, apărut pe listă ca „Loc de depozitare” (ex. Botosani, Dorohoi, Saveni, Trezorerie). |
| Activitate | Clasificare a persoanelor (ex. `Botosani (1Int)`, `Botosani (2C)`, `Trezorerie`). |
| Document | Intrare (repartizare), ieșire, transfer, schimbare de încadrare sau inventar inițial. |
| Inventar generat | Instantaneul (snapshot) situației la o dată, din care se tipăresc listele. |
| Tiraj | Toate listele unui inventar generat, în ordinea de tipărire. |

## 7. Reguli de domeniu (obligatorii)

### 7.1 Sursele de adevăr
- **Datele bunului** vin numai din exportul contabil și **nu se editează în aplicație**: existență, categorie, cont, denumire, U/M, serie, valoare, data amortizării integrale, casare, nr. inventar vechi.
- **Custodia** (cine, unde, ce activitate) se gestionează numai în aplicație.

### 7.2 Locație și activitate
- Stau **pe persoană, cu istoric**, în tabela `incadrare`; **nu pe bun**.
- O persoană are la orice dată **exact o încadrare**: o locație și o activitate.
- Locațiile și activitățile sunt nomenclatoare **independente**. Aceeași denumire poate fi și locație, și activitate (ex. Trezorerie); situația este frecventă.
- Un inventar la data D folosește încadrarea valabilă la D. O schimbare ulterioară nu modifică trecutul.
- Bunurile terților se țin pe o locație / activitate separată, deci ies automat pe liste distincte.

### 7.3 Gestiuni secundare (titular)
- Câteva persoane au mai multe gestiuni (ex. „NECHIFOR DAN ET2”, „AIONITOAIE CORNELIU VIRGIL et II”). Fiecare gestiune este o înregistrare separată în `persoana`.
- `persoana.titular_id` (opțional) trimite la persoana fizică. Un singur nivel: un titular nu are la rândul lui titular.
- Pe listă și declarații, „Gestiunea” = numele gestiunii; **la semnături apare numele titularului** (sau al gestiunii, dacă nu are titular).
- **E-mailul merge la titular**, într-un singur mesaj cu PDF-urile tuturor gestiunilor lui.
- Gestiunea secundară are propria încadrare și propriile documente.

### 7.4 Documente
| Tip (`document.tip`) | Efect |
| --- | --- |
| `INITIAL` | Pune bunurile la persoane la data de start. Creat doar de importul inițial. |
| `INTRARE` | Repartizarea unui bun nou din contabilitate către o persoană. Data propusă = `ddoc` din export. |
| `IESIRE` | Bunul iese din evidență (casare, vânzare, transfer la altă unitate, minus la inventar). Propusă la sincronizare când bunul e casat; data = `ddoccas`. |
| `TRANSFER` | Bunul trece de la o persoană la alta (bon de mișcare). |
| `INCADRARE` | Persoana trece în altă locație și / sau activitate de la o dată. Asistentul arată bunurile persoanei; pentru fiecare, operatorul alege dacă o urmează sau se predă altcuiva din vechea locație. Predările devin documente `TRANSFER` cu aceeași dată. |

- Stări: `CIORNA` → `VALIDAT` → (opțional) `ANULAT`, cu motiv. Doar documentele `VALIDAT` intră în calculul stocului.
- Fiecare linie are `bun_id`, `persoana_de_la_id` (null la INITIAL / INTRARE) și `persoana_la_id` (null la IESIRE).
- Reguli de validare:
  1. Data documentului ≥ data inventarului inițial.
  2. La data documentului, bunul trebuie să fie la `persoana_de_la_id`, iar la INTRARE să nu fie la nimeni.
  3. **Ordine cronologică pe bun:** nu se validează o mișcare a unui bun dacă există deja o mișcare validată a aceluiași bun cu dată ulterioară. Astfel lanțul rămâne mereu consistent.
  4. Un bun ieșit nu mai poate fi mișcat.
  5. Anularea unui document validat e permisă doar dacă nu există mișcări ulterioare validate pe bunurile lui. Motivul e obligatoriu și se scrie în jurnal.
  6. Validarea sau anularea unui document cu dată ≤ D marchează `NEACTUALIZAT` orice inventar `GENERAT` la data D.
- Bunurile complet amortizate rămân pe liste până la ieșire.
- Operații utile: transfer în masă (toate bunurile unei persoane către alta), fișa bunului (istoric), fișa persoanei (încadrări, bunuri la zi).

### 7.5 Situația la o dată (`domain/stoc.py`)
Pentru fiecare bun: ultima linie de document `VALIDAT` cu `document.data ≤ D` (ordonată după `data`, apoi `document.id`). `persoana_la_id` din acea linie e deținătorul; dacă e null, bunul a ieșit. Locația și activitatea vin din încadrarea persoanei valabilă la D. Implementează cu o singură interogare (subinterogare cu `MAX` / funcție fereastră), nu în buclă pe bunuri.

### 7.6 Inventarul generat
- Parametri: data D și perimetrul (locații, activități, persoane, grupuri, categorii, conturi; implicit tot). Perimetrul se stochează normalizat ca JSON.
- Generarea **copiază** în `inventar_linie` toate câmpurile necesare tipăririi: nr. inventar, nr. vechi, denumire, U/M, categorie, cont, cont sintetic, preț, serie, data amortizării integrale, gestiune, titular, locație, activitate. Copiază și comisia fiecărei locații în `inventar_comisie`. **Listele se tipăresc numai din snapshot**, niciodată din calcul direct.
- Stări: `GENERAT` → `NEACTUALIZAT` (un document sau o sincronizare l-au afectat) → regenerare; `BLOCAT` (semnat). Ștergerea unui inventar blocat cere deblocare de către administrator, cu motiv.
- Regenerare = ștergere + generare cu aceiași parametri, în aceeași tranzacție. În jurnal se scrie numărul de linii înainte și după.
- La aceeași dată și același perimetru e permis un singur inventar activ.
- Înainte de generare, aplicația avertizează dacă ultima sincronizare e anterioară lui D sau dacă există bunuri nerepartizate.

## 8. Model de date (punct de plecare)

```
setare(cheie PK, valoare)                       -- unitate, unitate superioară, sigla, SMTP, nivel cont în margine
utilizator(id, username UQ, parola_hash, rol[ADMIN|OPERATOR|CONSULTARE], activ, persoana_id?)
locatie(id, cod UQ, denumire, activ)
activitate(id, cod UQ, denumire, activ)
comisie(id, locatie_id, valabil_de_la, valabil_pana_la?)
membru_comisie(id, comisie_id, nume, calitate[PRESEDINTE|MEMBRU], ordine)
persoana(id, nume, marca?, email?, titular_id? -> persoana, activ)
incadrare(id, persoana_id, locatie_id, activitate_id, valabil_de_la, document_id?, motiv?)
          UQ(persoana_id, valabil_de_la)
grup(id, denumire) ; grup_persoana(grup_id, persoana_id)
cont(id, simbol UQ, sintetic, categorie[MF|OI], denumire?)
bun(id, nr_inventar UQ, nr_inventar_vechi?, categorie, cont_id, denumire, um, serie?,
    pret Numeric(15,2), data_pif?, data_amortizare_integrala?, cod_clasificare?, durata_normala?,
    nr_doc_intrare?, data_doc_intrare?, nr_doc_casare?, data_casare?, explicatie_casare?,
    mentiuni?, prezent_in_export bool, actualizat_la)
document(id, tip, serie?, numar, data, explicatie?, motiv_iesire?, stare,
         creat_de, creat_la, validat_de?, validat_la?, anulat_de?, anulat_la?, motiv_anulare?)
linie_document(id, document_id, bun_id, persoana_de_la_id?, persoana_la_id?)
inventar(id, data, perimetru_json, stare, generat_de, generat_la, nr_linii, motiv_deblocare?)
inventar_linie(id, inventar_id, bun_id, ...câmpurile copiate, vezi §7.6)
inventar_comisie(id, inventar_id, locatie_id, membri_json)
sincronizare(id, fisier, incarcat_de, incarcat_la, stare, rezumat_json)
sincronizare_diferenta(id, sincronizare_id, tip, nr_inventar, bun_id?, detalii_json, actiune?, rezolvat)
trimitere_email(id, inventar_id, titular_id, adresa, stare[IN_ASTEPTARE|TRIMIS|EROARE], eroare?, trimis_la?, atasamente_json)
sablon(cod PK, subiect?, corp)                  -- e-mail, declarații
jurnal(id, la, utilizator_id?, username, ip, actiune, obiect_tip?, obiect_id?, detalii_json, rezultat)
```

- `jurnal` e **append-only**: în cod nu există update sau delete pe această tabelă.
- Indexuri: `linie_document(bun_id)`, `document(data, stare)`, `incadrare(persoana_id, valabil_de_la)`, `inventar_linie(inventar_id)`.
- Modelul se poate ajusta la implementare. Orice schimbare de concept (nu doar de câmp) se discută întâi.

## 9. Importuri

### 9.1 Exportul contabil `MF_BAZA` (.xls, o foaie `MF_BAZA`, 61 de coloane)
Același format pentru MF și OI. Coloanele folosite (restul se ignoră, **inclusiv `reev`, `dreev` și cele legate de reevaluare**):

| Coloană | Câmp | Observații |
| --- | --- | --- |
| `codinv` | `nr_inventar` | text; cheia de legătură |
| `mf_oi` | `categorie` | `M` → MF, `O` → OI |
| `den`, `um`, `seria` | denumire, U/M, serie | `strip()` |
| `cont` | cont | normalizare (mai jos) |
| `pinv` | `pret` | → `Decimal` |
| `damoc` | `data_amortizare_integrala` | apare în marginea listei MF |
| `dpf`, `dnf`, `codclas` | data PIF, durată normală, cod clasificare | informative |
| `nrdoc`, `ddoc` | document de intrare | `ddoc` = data propusă pentru repartizare |
| `nrdcas`, `ddoccas`, `explcas` | casare | completate → propunere de IESIRE |
| `codinv_v` | `nr_inventar_vechi` | poate avea dubluri; gol / 0 → null |
| `mentiuni` | `mentiuni` | |

Normalizări (`domain/normalizare.py`, cu teste):
- **Cont:** se păstrează doar cifrele și se grupează 3 + 2 + 2 + …: `8030000` → `803.00.00`; `303.02.00.04` rămâne la fel; `212.09.01` rămâne la fel. Contul sintetic = primele 3 cifre.
- **Date** în export: text `dd-Mon-yy` (`27-Nov-20`, `01-May-97`). `  -   -` sau gol → null. Acceptă și celule de tip dată xlrd. Anii din 2 cifre: 69–99 → 19xx, 00–68 → 20xx.
- `codinv` și `codinv_v` pot veni ca număr (`116647.0`) → text fără zecimale.

### 9.2 Extrasul din aplicația existentă (`Imp_Ap_Existenta.xlsx`, folosit o singură dată)
Un rând pe bun, coloanele: `Tip` (`MijloaceFixe` / `ObiecteInventar`), `Locatia`, `Activitatea`, `Persoana`, `NrInventar`, `NrInventarVechi` (0 = lipsă).

### 9.3 Importul inițial (`importuri/import_initial.py`)
1. Se citesc MF_BAZA (MF și OI) și extrasul. Se creează în memorie bunurile, conturile, persoanele, locațiile, activitățile și încadrările la data de start.
2. Se afișează raportul, **fără să se salveze nimic**:
   - **erori blocante:** nr. inventar din extras inexistent în export; `Tip` diferit de `mf_oi`; aceeași persoană cu locații sau activități diferite; nr. inventar duplicat în extras;
   - **avertismente:** bunuri din export fără persoană în extras; `NrInventarVechi` diferit de `codinv_v` (are prioritate exportul);
   - **nume foarte apropiate** (ex. „AIONITOAIE CORNELIU” vs „AIONITOAIE CORNELIU VIRGIL et II”): operatorul alege „aceeași persoană” (unificare) sau „gestiune secundară” (completează titularul). Similaritatea se calculează cu `difflib` (stdlib).
3. Numele se importă exact cum sunt; greșelile se corectează ulterior prin redenumire, pentru că persoana are id intern.
4. La confirmare se salvează totul într-o tranzacție și se creează documentul `INITIAL`, validat, plus o înregistrare în jurnal.

### 9.4 Sincronizarea anuală (`importuri/sincronizare.py`)
Se încarcă un export MF_BAZA nou. Aplicația îl compară cu ce știe și propune acțiuni. **Nimic nu se aplică fără confirmare.**

| Diferență | Acțiune propusă |
| --- | --- |
| Bun nou în export | intră la „nerepartizate”; operatorul face INTRARE către o persoană, data propusă `ddoc` |
| Bun cu `nrdcas` / `ddoccas` completate, încă activ | IESIRE cu data și numărul casării |
| Bun dispărut din export, fără casare | doar semnalat, pentru verificare |
| Valoare, cont, denumire, categorie, serie, `damoc`, `codinv_v` schimbate | actualizare la valorile din export, **fără istoric** |
| Bun în aplicație, absent din contabilitate | doar semnalat |

Orice actualizare aplicată marchează `NEACTUALIZAT` inventarele `GENERAT`, dar nu și pe cele `BLOCAT`. Raportul (totaluri pe categorie și cont, în ambele surse) se poate exporta în Excel sau PDF.

## 10. PDF-uri (ReportLab)

Modelele reale sunt în `docs/exemple/`. **Rezultatul trebuie comparat vizual cu ele.** Textul din antete (unitate, unitate superioară, sigla) vine din `setare`, nu e scris în cod.

### 10.1 Lista de inventariere (formular 14-3-12) — A4 vedere (landscape)
- O listă = o gestiune × un **cont sintetic** × o locație. PDF-uri separate pentru MF și OI.
- Ordinea tirajului: locație, activitate, gestiune, categorie, cont.
- **Antet, pe fiecare pagină:**
  - stânga: sigla, unitatea superioară (D.G.R.F.P. IASI), „Unitatea”, unitatea (A.J.F.P. BOTOSANI);
  - centru: „LISTA DE INVENTARIERE”, „Data: 28 noiembrie 2025” (luna în litere);
  - dreapta: „Magazia” = „Mijloace Fixe” / „Obiecte de inventar” + contul sintetic, „Gestiunea” = numele gestiunii, „Loc de depozitare” = locația, „Pagina” = numărul paginii **în cadrul listei**.
- Deasupra antetului, cursiv, aliniat la dreapta: `Mijloace Fixe - Cont: 213, Loc depozitare - A.J.F.P. BOTOSANI, Gestionar: HRITCU MARCELA`.
- **Coloane:**

| Nr. | Conținut |
| --- | --- |
| 0 | Nr. crt. |
| 1 | Denumirea bunurilor inventariate; seria pe al doilea rând, mai mic |
| 2 | Cod / nr. inventar; nr. inventar vechi alături, mic și cursiv (doar dacă există) |
| 3 | U/M |
| 4 | Stocuri **scriptice** = 1,00 |
| 5 | Stocuri **faptice** (gol) |
| 6–7 | Diferențe cantitative plus / minus (goale) |
| 8 | Preț unitar |
| 9 | Valoare contabilă (pe fiecare rând) |
| 10–11 | Diferențe valorice plus / minus (goale) |
| 12 | Valoarea de inventar (goală) |
| 13–14 | Depreciere: valoare, motiv (cod) (goale) |

  **Ordinea corectă este scriptice (4), apoi faptice (5).** Lista OI din exemplu le are inversate; acela e un defect al modelului vechi, nu se copiază.
- Rândul cu numerele coloanelor (0…14) apare sub capul de tabel, pe fiecare pagină.
- **Marginea stângă**, în afara tabelului, pe fiecare rând: contul bunului (nivel configurabil, implicit 2 niveluri, ex. `303.02`) și, la MF, data amortizării integrale (`dd.mm.yyyy`).
- La sfârșitul listei: rândul „Total pentru gestiunea <GESTIUNE> / <LOCAȚIE>”, cu totalul coloanei 9. Apoi mențiunea gestionarului (pct. 33): „Toate bunurile din gestiune au fost inventariate in prezenta mea si nu am obiectii cu privire la modul de efectuare a inventarierii.” (corectat față de model, care are „invetarierii”) și „Responsabil / Gestionar / Utilizator Mijloace Fixe, <TITULAR>”.
- **Blocul de semnături, pe fiecare pagină** (normele cer semnarea fiecărei file): „Numele si prenumele” / „Semnatura” × „Comisia de inventariere” (membrii comisiei locației), „Responsabil / Gestionar / Utilizator Mijloace Fixe” (sau „… Ob. Inventar”) = titularul, „CONTABILITATE”.
- **Subsol:** stânga „Pagina X din Y”, numerotare **pe tot tirajul** (canvas cu numărare amânată, modelul `NumberedCanvas`); dreapta „COD: 14-3-12”.
- Coloanele 5–7 și 10–14 rămân goale: se completează de mână la inventarul fizic.
- Verificare cu exemplele: HRITCU MARCELA, MF, cont 213: 3 bunuri, total **11658,74**; CONSTANTIN ANA, OI, cont 303, Trezorerie: 7 bunuri, total **1014,85**.

### 10.2 Declarația de inventar (de început) — A4 portret, una pe gestiune × categorie
Model: `docs/exemple/extrSaveni_Decl_ObInv.pdf`.
- Antet stânga: „Agenţia Naţională de Administrare Fiscală” / „DGRFP IAŞI - A.J.F.P. Botoşani” (din setări). Dreapta sus, cursiv: „<Locație> - <Mijloace Fixe | Obiecte de Inventar>”.
- Titlu: „DECLARAŢIE DE INVENTAR”.
- „Subsemnatul <TITULAR>, în calitate de gestionar / utilizator al <obiectelor de inventar | mijloacelor fixe> declar:”, apoi punctele (1)–(11) cu linii punctate. **Punctele 8–9 nu se precompletează.**
- Semnături: „DATĂ ÎN FAŢA NOASTRĂ:” (membrii comisiei locației) | „GESTIONAR” (titularul). Jos: „Data: <data inventarului>”.
- Textul punctelor vine din `sablon`.

### 10.3 Declarația de sfârșit de inventar — **două pe o pagină A4**
Model: `docs/exemple/extrSaveni_SfInv_ObInv.pdf`. Document separat de liste.
- Același antet, „<Locație> - <Categorie>”, titlul „DECLARAŢIE DE SFÂRŞIT DE INVENTAR”.
- „Subsemnatul <TITULAR> gestionar / utilizator al depozitului / gestiunii <categoria> din cadrul <unitate> locaţia <Locație> declar că:”
  - „toate bunurile din gestiune AU FOST / NU AU FOST inventariate şi consemnate în listele de inventar în prezenţa mea;”
  - „am / nu am obiecţii cu privire la modul în care s-a efectuat inventarierea.”
- Semnături: „Gestionar,” <TITULAR> | „Comisia de Inventar:” <membri>. „Data: …”.

### 10.4 Reguli comune
- Font TTF cu diacritice (DejaVu Sans și varianta Bold, înregistrate o singură dată). Numele se tipăresc exact cum sunt în baza de date (pot avea ş/ţ cu sedilă).
- Generarea tirajului complet (~300 de pagini) trebuie să dureze sub un minut.
- Nume fișiere: `Inventar_<yyyy-mm-dd>_<gestiune>_MF.pdf` / `_OI.pdf`. Numele gestiunii se simplifică pentru sistemul de fișiere (fără diacritice și spații).

## 11. Alte funcții

- **Centralizatoare** (din snapshot, fără semnături): pe categorii (MF/OI → cont), pe conturi, pe locații (→ categorie → cont), pe activități, pe gestiuni. Coloane: număr de bunuri, valoare; subtotaluri și total general. Ieșire: ecran, PDF, Excel.
- **Export** (situații ad-hoc): snapshot complet sau filtrat, `.xlsx` și `.csv`, un rând pe bun, toate câmpurile din `inventar_linie`.
- **Listări și filtre** (aceleași pentru liste, declarații, centralizatoare și e-mail): locații, activități, gestiuni individuale, grupuri, categorie, conturi, „doar gestiunile cu bunuri”.
- **E-mail:**
  - se trimite doar titularilor cu adresă; cei fără adresă apar într-o listă separată;
  - un mesaj per titular, cu PDF-urile MF și OI ale tuturor gestiunilor lui;
  - subiectul și corpul vin din `sablon`, cu câmpurile `{nume}`, `{data}`, `{locatie}`;
  - înainte de trimitere: previzualizare (destinatari, atașamente) și confirmare;
  - trimiterea rulează pe un fir separat, iar starea se salvează pe fiecare destinatar; se poate retrimite doar la cei cu eroare;
  - setările SMTP le face doar administratorul, iar parola se criptează cu Fernet.
- **Jurnal:** autentificări (reușite și eșuate), modificări de nomenclatoare, documente, importuri, sincronizări, generări, ștergeri, deblocări, PDF, e-mail, export, schimbări de setări și drepturi. Ecran de consultare (doar administratorul), cu filtre și export CSV.
- **Roluri:** `ADMIN` — tot; `OPERATOR` — date, documente, inventare, tipărire, e-mail, pe toate locațiile; `CONSULTARE` — doar citire și listare. Verificarea rolului se face cu un decorator pe rute **și** în serviciu.
- **Securitate:** CSRF pe toate formularele, sesiuni cu expirare, parole cu hash, fără date sensibile în log-urile tehnice.

## 12. Fișiere de exemplu (`docs/exemple/`)

Datele reale nu se pun în teste; testele folosesc fixture-uri sintetice construite după structura lor.

| Fișier | Ce este |
| --- | --- |
| `Hritcu_Marcela.pdf` | Listă MF, cont 213, 3 bunuri, total 11658,74 |
| `ana_constantin.pdf` | Listă OI, cont 303, Trezorerie, 7 bunuri, total 1014,85 |
| `extrSaveni_Decl_ObInv.pdf` | Declarația de inventar (de început), OI, Săveni |
| `extrSaveni_SfInv_ObInv.pdf` | Declarații de sfârșit, două pe pagină (Dorohoi, Săveni) |
| `MIJLOACE_FIXE.xls`, `OBIECTE_DE_INVENTAR.xls` | Export MF_BAZA (câteva rânduri) |
| `Imp_Ap_Existenta.xlsx` | Extras din aplicația existentă (20 de rânduri) |

## 13. Teste (obligatorii pentru `domain/` și `importuri/`)

- `stoc`: situația la diverse date, după INITIAL, TRANSFER, IESIRE, INTRARE; bun ieșit; documente CIORNA ignorate.
- Regula cronologică pe bun; anularea blocată de mișcări ulterioare.
- `incadrare`: valabilă la o dată, inclusiv exact la data schimbării.
- Snapshot imuabil: după un document nou, un inventar `BLOCAT` rămâne identic, iar unul `GENERAT` devine `NEACTUALIZAT`.
- Normalizarea conturilor și a datelor (toate cazurile din §9.1).
- Import inițial: fiecare eroare blocantă și fiecare avertisment din §9.3.
- Sincronizare: fiecare rând din tabelul §9.4.
- PDF: test de fum. Se generează lista pentru un fixture cu 3 bunuri, se extrage textul cu `pypdf` (dependență doar de test) și se verifică totalul, „Pagina 1 din 1”, „COD: 14-3-12” și diacriticele.
- Testele folosesc SQLite în memorie, cu o bază nouă pentru fiecare test.

## 14. Plan de lucru pe faze

Lucrează **o fază pe rând**. La finalul fiecărei faze: teste verzi, scurt rezumat pentru utilizator și **oprire până la confirmare**. Actualizează secțiunea „Stare” de mai jos.

| Fază | Conținut | Gata când |
| --- | --- | --- |
| 0 | Schelet: `create_app`, config, extensii, SQLite WAL, migrări, autentificare, roluri, jurnal, layout de bază, `creeaza-admin` | login / logout funcționează, iar jurnalul scrie |
| 1 | Nomenclatoare: locații, activități, persoane (cu titular), încadrări cu istoric, grupuri, comisii pe locație, setări | CRUD complet, fără ștergeri fizice |
| 2 | Import inițial (§9.3) cu raport și confirmare | exemplele din `docs/exemple/` se importă, iar nepotrivirile sunt raportate corect |
| 3 | Documente (§7.4): ciornă, validare, anulare, asistent schimbare încadrare, transfer în masă, fișa bunului, fișa persoanei, situația la zi | toate regulile au teste |
| 4 | Generare inventar (§7.6): snapshot, stări, regenerare, blocare / deblocare | teste de imuabilitate verzi |
| 5 | PDF: lista 14-3-12 (§10.1), apoi declarațiile (§10.2, §10.3) | comparat vizual cu modelele; totalurile din §10.1 corecte |
| 6 | Centralizatoare, export Excel / CSV, filtre de listare | |
| 7 | E-mail (§11) | trimitere testată pe un SMTP de test (ex. `aiosmtpd` local sau un server de test al instituției) |
| 8 | Sincronizare anuală (§9.4) | fiecare tip de diferență are test |
| 9 | Livrare: `scripts/backup.py`, `scripts/instalare_serviciu.ps1` (NSSM + Waitress), `README.md` de instalare | instalare reprodusă pe un Windows curat |

## 15. Cum lucrezi în acest proiect

- **Când specificația e ambiguă, întreabă.** Nu inventa reguli contabile sau legale.
- Nu schimba deciziile din §2 și §7 fără acord explicit.
- Scrie întâi testele pentru logica de domeniu, apoi codul.
- Modificările de schemă se fac doar prin migrări Alembic, niciodată manual pe baza de date.
- Nu șterge și nu rescrie fișierele din `docs/exemple/`.
- Păstrează fișierele mici și ușor de citit. Un modul de peste ~400 de linii e semn că trebuie împărțit.
- Comentariile și docstring-urile sunt în română și explică **de ce**, nu ce.

## Stare

- Faza 0 — **terminată** (2026-10-13): schelet, SQLite WAL, migrare inițială (`utilizator`, `jurnal` cu triggere append-only), autentificare, roluri (`drepturi.py` + `web.rol_necesar`), jurnal, layout, `creeaza-admin`. 15 teste verzi.
- Faza 1 — **terminată** (2026-10-13): locații, activități, persoane cu titular, încadrări cu istoric (`domain/incadrare.py`, inclusiv `incadrari_la(D)` cu funcție fereastră), grupuri, comisii pe locație, setări + siglă, administrare utilizatori, schimbare parolă proprie. 50 de teste verzi.
  - Încadrările se adaugă doar la capătul istoricului; se poate corecta doar ultima.
  - O comisie nouă o închide automat pe cea deschisă (cu o zi înainte); perioadele nu se suprapun.
  - Unicitatea (cod, nume persoană, grup) e fără diferență de majuscule și se verifică în Python (`lower()` din SQLite nu știe diacritice).
  - `migrations/env.py` dezactivează `foreign_keys` pe durata migrărilor SQLite (batch recreează tabelele) și rulează `foreign_key_check` la final.
  - TODO-uri lăsate în cod pentru fazele 3–4 (schimbarea încadrării prin asistent, blocarea dezactivării cu bunuri, marcare NEACTUALIZAT la corectare).
- Faza 2 — **terminată** (2026-10-13): modele `cont`, `bun`, `document`, `linie_document`; `domain/normalizare.py`, `formatare.py`; cititoarele `importuri/mf_baza.py` și `importuri/extras.py`; `importuri/import_initial.py` (analiză fără salvare → decizii pe nume apropiate → confirmare atomică cu document INITIAL validat); ecranul „Import”. 135 de teste verzi.
  - Importul inițial se face o singură dată, pe o bază fără persoane și fără bunuri; locațiile și activitățile existente se refolosesc (după cod, fără diferență de majuscule).
  - Data de start o alege operatorul la încărcare; este data documentului INITIAL.
  - Nume apropiate: identice fără diacritice/majuscule, unul prefix al celuilalt sau `difflib` ≥ 0,85. Fiecare pereche cere o decizie explicită: diferite / unificare (A sau B) / gestiune secundară (în ambele sensuri).
  - Bunurile casate în export: nerepartizate → normal, fără avertisment; repartizate în extras → avertisment (ieșirea se propune la sincronizare).
  - Fișierele încărcate stau în `instance/importuri/<token>/` (legate de utilizator, șterse după confirmare sau după 24 h).
  - Pe exemplele din `docs/exemple/`: 20 de erori blocante (numerele din extras nu există în exporturile-eșantion), 7 bunuri nerepartizate, 1 pereche de nume apropiate — comportament corect pentru niște fișiere-eșantion care nu se corespund.
- Faza 3 — **terminată** (2026-10-13): `domain/stoc.py` (situația la o dată, o singură interogare cu funcție fereastră), `domain/documente.py` (ciornă / validare / anulare, toate regulile §7.4), `domain/schimbare_incadrare.py` (asistentul INCADRARE cu predări → TRANSFER validate), ecrane: documente, situația bunurilor (filtre + paginare), fișa bunului, fișa persoanei cu bunuri la zi, transfer în masă. 180 de teste verzi.
  - Regula cronologică și anularea folosesc ordinea stocului, (data, document.id): „ulterior” înseamnă dată mai mare **sau** aceeași dată cu id mai mare.
  - Validarea / anularea / asistentul iau întâi lacătul de scriere SQLite (`rezerva_scrierea`); `tests/domain/test_concurenta.py` dovedește că fără el același bun ar fi mutat de două ori.
  - Orice schimbare de încadrare trece prin asistent și creează un document INCADRARE (și pentru persoane fără bunuri). Anularea lui șterge încadrarea creată (doar dacă e ultima a persoanei); transferurile de predare se anulează separat. Încadrările venite din document nu se „corectează”.
  - Regula 1 (data ≥ inventarul inițial) se aplică doar dacă există documentul INITIAL.
  - Motive de ieșire: CASARE, VANZARE, TRANSFER_UNITATE, MINUS_INVENTAR.
  - O persoană nu se dezactivează cât are bunuri (inclusiv prin documente cu dată viitoare).
- Faza 4 — **terminată** (2026-10-13): modele `inventar`, `inventar_linie`, `inventar_comisie`; `domain/generare.py` (perimetru normalizat, avertismente, generare, regenerare, blocare / deblocare, ștergere); `domain/neactualizare.py` (regula 6, apelată din validare, anulare, asistentul de încadrare și corectarea încadrării); ecranele „Inventare”. 201 teste verzi.
  - Perimetrul: listă goală = toate; dimensiunile se combină cu ȘI; gestiunile alese direct și cele din grupuri se adună; conturile sunt sintetice. UQ(data, perimetru_json).
  - `inventar_linie.titular` / `titular_id` = persoana fizică (titularul gestiunii secundare sau gestiunea însăși): la ea merg semnătura și e-mailul.
  - Comisia se copiază pentru fiecare locație din instantaneu; o locație fără comisie primește listă goală și un avertisment la generare.
  - Regenerarea păstrează numărul inventarului (înlocuiește liniile în aceeași tranzacție).
  - Blocarea doar din GENERAT; deblocarea (ADMIN, cu motiv) duce în NEACTUALIZAT, deci reblocarea cere regenerare.
  - Avertismentele se arată înainte de generare și cer confirmare („Generează oricum”).
  - Nu marchează NEACTUALIZAT (de discutat): redenumirea unei persoane, schimbarea titularului, modificarea comisiei — instantaneul păstrează valorile vechi până la regenerare.
- Faza 5 — **terminată** (2026-10-13): `pdf/comun.py` (fonturi DejaVu Sans + Condensed + Oblique în `pdf/fonts/`, `canvas_numerotat`, `nume_fisier`), `pdf/lista.py` (14-3-12 desenat pe pânză cu paginare proprie), `pdf/declaratii.py` (Platypus: început 1/pagină, sfârșit 2/pagină), `tiparire.py` (serviciu: numai din instantaneu, jurnal PDF_LISTE / PDF_DECLARATII), tabela `sablon` + ecranul „Șabloane de text”. 212 teste verzi; tiraj de ~300 de pagini în ~1,3 s.
  - Urmează §10.1 acolo unde diferă de modele: seria pe rândul 2 din col. 1 (nu în col. 13), valoarea pe fiecare rând în col. 9, scriptice înaintea faptice, „inventarierii”.
  - Greșeli de tipar corectate în textul declarațiilor: „fără”, „s-au întocmit”, „la contabilitate”, „inventarierea”.
  - „Loc de depozitare” = denumirea locației; pentru „A.J.F.P. BOTOSANI” ca în model, se redenumește locația.
  - Declarațiile gestiunilor secundare au în colțul din dreapta sus și numele gestiunii (altfel ar fi identice cu ale titularului).
  - Un inventar NEACTUALIZAT nu se tipărește (se cere regenerare). Tipărirea e permisă și rolului CONSULTARE.
  - Declarațiile folosesc DejaVu Sans (modelele: Times / Arial), conform §2.
- Faza 6 — **terminată** (2026-10-13): `domain/filtre.py` (filtrul de listare = clasa `Perimetru`, aplicat pe `inventar_linie`; `descriere()`), `domain/centralizatoare.py` (5 tipuri, ierarhic cu subtotaluri și total general), `pdf/centralizatoare.py`, `export/excel.py` (linii .xlsx / .csv, centralizator .xlsx), `rapoarte.py` (serviciu cu jurnal CENTRALIZATOR / EXPORT); pagina „Listări” a inventarului cu filtrul comun pentru liste, declarații, centralizatoare și export. Fără migrare. 226 de teste verzi.
  - Centralizatoare: categorii (categorie → cont analitic), conturi (sintetic → analitic), locații (locație → categorie → sintetic), activități (la fel), gestiuni (gestiune → categorie).
  - CSV: separator „;”, BOM UTF-8, virgulă zecimală, date dd.mm.yyyy (pentru Excel în limba română).
  - Fișierele (PDF / Excel / CSV) nu se produc dintr-un inventar NEACTUALIZAT; centralizatorul pe ecran se poate vedea.
  - „Doar gestiunile cu bunuri”: instantaneul conține doar gestiunile cu bunuri, deci filtrul e implicit mereu activ — de discutat dacă se vor declarații și pentru gestiunile fără bunuri.
- Faza 7 — **terminată** (2026-10-13): `criptare.py` (Fernet, cheie în `instance/secret.key`), `email/smtp.py` (setări SMTP, `Conexiune` refolosită pe lot), `email/trimitere.py` (previzualizare, lot, `trimite_lot`, retrimitere, mesaj de probă), tabela `trimitere_email` (cu `lot`, `subiect`, `corp`), șablonul `email_inventar` cu câmpurile {nume} {data} {locatie} validate la salvare; ecrane: previzualizare + confirmare, starea lotului (htmx la 2 s), lista trimiterilor, Administrare → E-mail (SMTP). 240 de teste verzi, inclusiv pe un SMTP local (aiosmtpd, dependență doar de test); probă reală cu Waitress + fir separat: 5/5 mesaje.
  - Un mesaj pe titular, cu PDF-urile MF / OI ale tuturor gestiunilor lui; atașamentele se generează la trimitere, din instantaneu; filtrul de listare se aplică.
  - O eroare de conexiune la server se aplică întregului rest al lotului (fără să aștepte expirarea la fiecare destinatar).
  - Retrimiterea: cei cu EROARE și, dacă firul nu mai rulează (de ex. repornire), cei rămași IN_ASTEPTARE.
  - În teste, `EMAIL_SINCRON=True` rulează trimiterea pe loc.
  - La cererea utilizatorului (după faza 7): e-mailul conține, pe gestiune × categorie, lista **și** declarațiile de început și de sfârșit.
- Faza 8 — **terminată** (2026-10-13): modele `sincronizare`, `sincronizare_diferenta`; `importuri/sincronizare.py` (analiză → încărcare cu diferențele salvate → aplicare atomică a celor bifate, cu verificarea că exportul și situația nu s-au schimbat între timp; abandonare); raport (totaluri pe categorie și cont în ambele surse + diferențe) pe ecran, PDF și Excel; meniul „Contabilitate”. 259 de teste verzi; verificat și pe exporturile reale din `docs/exemple/`.
  - Tipuri: BUN_NOU (creat, rămâne nerepartizat), CASARE (un document IESIRE validat pe fiecare casare nr. + dată; fără dată → doar semnalat), MODIFICAT (toate câmpurile din export, fără istoric), DISPARUT (era în export, acum lipsește, neieșit) și ABSENT (deja lipsea, încă activ) — ultimele două doar semnalate.
  - La aplicare, `prezent_in_export` se actualizează pentru toate bunurile; orice actualizare de date marchează NEACTUALIZAT inventarele GENERAT (orice dată), nu și pe cele BLOCAT.
  - `data_ultimei_sincronizari` = cea mai recentă dintre importul inițial și sincronizările aplicate.
  - Fișierele încărcate stau în `instance/sincronizari/<director>/` (necesare la aplicare).
- Faza 9 — **terminată** (2026-10-13): `scripts/backup.py` (API online SQLite, `integrity_check` pe copie, fișierele din `instance/`, rotație, cod de ieșire pentru Task Scheduler), `scripts/instalare_serviciu.ps1` (PowerShell 5.1, UTF-8 cu BOM; NSSM + Waitress, sarcina de backup, `-Simulare`, `-Dezinstalare`), `README.md` de instalare (offline din `wheels/`, IIS / Caddy, backup / restaurare, actualizare). În plus: ecranul **Jurnal de acțiuni** (§11, doar admin, filtre, export CSV), care lipsea din fazele anterioare. 266 de teste verzi.
  - Instalarea reprodusă după README într-un director curat (pachete descărcate → instalare `--no-index` → migrări → admin → Waitress cu parametrii serviciului → backup → restaurare → toate testele verzi). NSSM și sarcina programată verificate doar în `-Simulare` (nu există NSSM / drepturi de administrator pe mașina de dezvoltare); Python 3.13 în loc de 3.12.
  - În spatele proxy-ului, aplicația trebuie să vadă numele public al site-ului (Host păstrat sau `X-Forwarded-Host`), altfel CSRF strict pe HTTPS refuză formularele; Waitress are încredere doar în proxy-ul de pe 127.0.0.1. Pentru IIS: `preserveHostHeader=True` (în README).
  - În șirurile din `.ps1` nu se folosesc ghilimele „ ”: PowerShell le tratează ca delimitatori.
- **Toate fazele sunt terminate.** Rămân deschise: declarații pentru gestiunile fără bunuri (filtrul „doar gestiunile cu bunuri”) și marcarea NEACTUALIZAT la redenumiri / schimbări de comisie — ambele așteaptă decizia utilizatorului.
- Convenție stabilită: serviciile publice primesc `(session, actor, ...)`, verifică rolul, scriu în jurnal și fac ele `commit`; `jurnal.scrie` nu face commit.
- Dezvoltarea rulează pe Python 3.13 (3.12 nu e instalat pe mașina de dezvoltare).
- Cerințele complete (cu justificări) sunt în documentul „Aplicație liste de inventariere — Cerințe”. Acest fișier conține tot ce e necesar pentru implementare.
