# Liste de inventariere — instalare și administrare

Aplicație web internă pentru evidența bunurilor pe gestiuni, locații și activități și pentru listele de
inventariere (formular 14-3-12), declarații, centralizatoare, export și e-mail. Rulează pe un server Windows,
iar utilizatorii lucrează din browser. Pe stațiile utilizatorilor nu se instalează nimic.

Arhitectura pe server:

```
browser ──HTTPS──> IIS sau Caddy (proxy) ──HTTP 127.0.0.1:8080──> Waitress (serviciu Windows, NSSM) ──> SQLite
```

## 1. Ce trebuie pe server

| Componentă | Observații |
| --- | --- |
| Windows Server 2016+ / Windows 10+ | cu PowerShell 5.1 (inclus) |
| Python 3.12 (64 de biți) | de la python.org; la instalare bifați „Add python.exe to PATH” |
| NSSM 2.24 | https://nssm.cc — un singur `nssm.exe`, de pus de ex. în `C:\nssm\` |
| IIS (cu URL Rewrite + ARR) sau Caddy | pentru HTTPS; vezi §5 |

Serverul **nu are nevoie de internet la rulare**: Bootstrap, htmx și fonturile sunt incluse în aplicație.
Pentru instalare, pachetele Python se descarcă pe un alt calculator (§2.1).

## 2. Instalare

### 2.1. Pachetele Python, pe un calculator cu internet

Pe un calculator cu aceeași versiune de Python (3.12, 64 de biți, Windows):

```powershell
pip download -r requirements.txt -d wheels
```

Se copiază pe server directorul aplicației **și** directorul `wheels`.

### 2.2. Pe server

Exemplul folosește `D:\Inventare`; se poate alege orice director.

```powershell
cd D:\Inventare
python -m venv .venv
.venv\Scripts\python -m pip install --no-index --find-links wheels -r requirements.txt

.venv\Scripts\flask --app inventar db upgrade          # creează baza de date în instance\inventar.db
.venv\Scripts\flask --app inventar creeaza-admin       # primul administrator (cere utilizator și parolă)
```

Probă rapidă, fără serviciu:

```powershell
.venv\Scripts\waitress-serve --listen=127.0.0.1:8080 inventar.wsgi:app
```

Deschideți `http://127.0.0.1:8080` pe server, autentificați-vă, apoi opriți cu Ctrl+C.

### 2.3. Serviciul Windows și backup-ul zilnic

Dintr-un PowerShell pornit **ca Administrator**:

```powershell
cd D:\Inventare
powershell -ExecutionPolicy Bypass -File scripts\instalare_serviciu.ps1 `
    -Nssm C:\nssm\nssm.exe -Port 8080 -DirectorBackup E:\Backup\Inventare -OraBackup 02:00
```

Scriptul:
- aplică migrările;
- instalează serviciul **Inventare** (pornire automată, repornire la cădere, jurnal rotit în `logs\serviciu.log`);
- creează sarcina programată **„Inventare - backup zilnic”**;
- verifică faptul că aplicația răspunde.

Parametri utili:
- `-Simulare` doar afișează ce ar face;
- `-Dezinstalare` șterge serviciul și sarcina, dar lasă datele neatinse;
- `-FaraProxy` e doar pentru probe pe HTTP simplu, fără IIS sau Caddy în față.

> Dacă portul 8080 e ocupat pe server, alegeți altul cu `-Port` și folosiți-l și în configurarea proxy-ului.

## 3. Prima configurare (în aplicație, ca administrator)

1. **Administrare → Setări:** unitatea, unitatea superioară, antetele declarațiilor, nivelul contului în marginea listei și sigla.
2. **Administrare → E-mail (SMTP):** serverul instituției, apoi „Mesaj de probă”.
3. **Administrare → Utilizatori:** operatorii (OPERATOR) și cei care doar consultă (CONSULTARE).
4. **Nomenclatoare:** locații, activități și comisiile de inventariere pe locație.
5. **Contabilitate → Import inițial:**
   - se încarcă exportul MF_BAZA (MF și OI) și extrasul din aplicația existentă, apoi se citește raportul;
   - se decide pentru numele apropiate;
   - se confirmă.

   Persoanele se creează din extras, deci importul se face **înainte** de a adăuga persoane manual.

## 4. Configurare (opțional)

Implicit nu e nevoie de nimic: baza e `instance\inventar.db`, iar cheile se generează singure în `instance\`.
Se poate suprascrie prin `instance\config.py` sau prin variabile de mediu (setate pentru serviciu cu
`nssm set Inventare AppEnvironmentExtra ...`):

| Variabilă | Efect |
| --- | --- |
| `INVENTAR_DATABASE_URI` | altă cale a bazei, ex. `sqlite:///E:/Date/inventar.db` |
| `INVENTAR_SECRET_KEY` | cheia sesiunilor (implicit: `instance\flask_secret.key`) |
| `INVENTAR_COOKIE_SECURE` | `1` = cookie-uri doar pe HTTPS (scriptul o setează automat) |

Fișiere din `instance\` care **nu se pierd**: `inventar.db`, `secret.key` (cheia cu care e criptată parola SMTP),
`flask_secret.key`, `sigla.png`. Backup-ul le copiază pe toate.

## 5. HTTPS: IIS sau Caddy

Aplicația ascultă doar pe `127.0.0.1`. Proxy-ul publică HTTPS în rețeaua internă. Serviciul acceptă de la
127.0.0.1 antetele `X-Forwarded-For` (IP-ul real, pentru jurnal), `X-Forwarded-Proto` și `X-Forwarded-Host`.

> **Important:** aplicația trebuie să vadă **numele public** al site-ului (de exemplu `inventar.intern.local`).
> Îl vede fie din antetul `Host` păstrat de proxy, fie din `X-Forwarded-Host`. Altfel, pe HTTPS, toate
> formularele sunt refuzate cu „The referrer does not match the host”.

**Caddy** (`Caddyfile`, cu certificatul instituției):

```
inventar.intern.local {
    tls C:\certificate\inventar.crt C:\certificate\inventar.key
    reverse_proxy 127.0.0.1:8080
}
```

Caddy păstrează antetul `Host` și trimite singur `X-Forwarded-For`, `X-Forwarded-Proto` și `X-Forwarded-Host`.
Se instalează și el ca serviciu, tot cu NSSM.

**IIS:**
1. Instalați modulele *URL Rewrite* și *Application Request Routing*, apoi activați proxy-ul (ARR → Server Proxy Settings → Enable proxy).
2. Pe site, legați HTTPS (binding) cu certificatul instituției.
3. Adăugați o regulă de rescriere *Reverse Proxy* către `127.0.0.1:8080`.
4. **Păstrați antetul Host** (ARR îl rescrie implicit), dintr-un prompt de Administrator:
   `%windir%\system32\inetsrv\appcmd.exe set config -section:system.webServer/proxy /preserveHostHeader:True /commit:apphost`
5. Adăugați la variabilele permise (*Allowed Server Variables*) `HTTP_X_FORWARDED_PROTO`, setat la `https` în regulă. `X-Forwarded-For` îl adaugă ARR.
6. Încărcările de fișiere (exporturi) pot avea câțiva MB: verificați *Request Filtering → Maximum allowed content length* (aplicația acceptă până la 50 MB).

## 6. Backup și restaurare

Backup-ul zilnic face o copie consistentă a bazei, chiar cu aplicația pornită (API-ul online SQLite), îi
verifică integritatea și o pune în `E:\Backup\Inventare\inventar_AAAA-LL-ZZ_HHMMSS\`, împreună cu fișierele din
`instance\`. Se păstrează ultimele 30. Manual:

```powershell
.venv\Scripts\python scripts\backup.py --destinatie E:\Backup\Inventare
```

Țineți directorul de backup pe alt disc decât aplicația și copiați-l periodic în afara serverului.

**Restaurare:**

```powershell
nssm stop Inventare
# se mută deoparte instance\inventar.db* (inclusiv -wal și -shm), apoi:
copy E:\Backup\Inventare\inventar_2026-03-01_020000\* D:\Inventare\instance\
nssm start Inventare
```

## 7. Actualizarea aplicației

```powershell
nssm stop Inventare
.venv\Scripts\python scripts\backup.py --destinatie E:\Backup\Inventare   # întâi un backup
# se copiază noua versiune peste director (fără instance\, .venv\, logs\)
.venv\Scripts\python -m pip install --no-index --find-links wheels -r requirements.txt
.venv\Scripts\flask --app inventar db upgrade
nssm start Inventare
```

## 8. Unde se uită când ceva nu merge

| Problemă | Unde |
| --- | --- |
| Serviciul nu pornește | `logs\serviciu.log`; `nssm status Inventare` |
| Cine a făcut o modificare | în aplicație: Administrare → Jurnal de acțiuni (cu export CSV) |
| E-mailurile nu pleacă | E-mail → trimiterea respectivă (eroarea pe fiecare destinatar); Administrare → E-mail (SMTP) → Mesaj de probă |
| Backup-ul nu rulează | Task Scheduler → „Inventare - backup zilnic” → Istoric (codul de ieșire nenul înseamnă eroare) |
| „Parola SMTP nu poate fi decriptată” | `instance\secret.key` a fost înlocuit; reintroduceți parola în Administrare → E-mail (SMTP) |

## 9. Dezvoltare

Instrucțiunile pentru dezvoltare și regulile proiectului sunt în `CLAUDE.md`. Pe scurt:

```powershell
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\flask --app inventar run --debug
.venv\Scripts\pytest
```
