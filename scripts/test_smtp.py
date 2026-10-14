"""Diagnostic pentru trimiterea e-mailului: arată dialogul complet cu serverul SMTP.

    .venv\\Scripts\\python scripts\\test_smtp.py destinatar@exemplu.ro [--expeditor adresa@exemplu.ro]

Folosește setările SMTP salvate în aplicație (parola se decriptează local și nu se afișează).
Afișează comenzile și răspunsurile serverului, adresele refuzate de server și
capabilitățile anunțate la EHLO. Un răspuns „250” la final înseamnă doar că serverul a
acceptat mesajul; livrarea mai departe se verifică în jurnalul serverului de e-mail.
"""
import argparse
import smtplib
import ssl
import sys
from email.utils import formatdate
from pathlib import Path

# Consola Windows (cp1252) nu poate afișa diacriticele din mesaje.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RADACINA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADACINA))

from inventar import create_app  # noqa: E402
from inventar.email.smtp import TIMP_ASTEPTARE, citeste_smtp, construieste_mesaj  # noqa: E402
from inventar.extensions import db  # noqa: E402


def _masca(linie: str) -> str:
    """Debug-ul smtplib ar afișa credențialele (AUTH ... base64); le înlocuim."""
    return "send: 'AUTH ***'" if "AUTH" in linie.upper() and "send:" in linie else linie


class _SMTP(smtplib.SMTP):
    def _print_debug(self, *args):
        text = " ".join(str(a) for a in args)
        print(_masca(text) if "AUTH" in text.upper() and "send" in text else text)


class _SMTP_SSL(smtplib.SMTP_SSL):
    _print_debug = _SMTP._print_debug


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("destinatar")
    parser.add_argument("--expeditor", help="înlocuiește adresa expeditorului din setări (pentru comparație)")
    argumente = parser.parse_args()

    app = create_app()
    with app.app_context():
        s = citeste_smtp(db.session, Path(app.instance_path))
    if not s.configurat:
        print("Setările SMTP nu sunt completate (server și adresa expeditorului).")
        return 2
    expeditor = argumente.expeditor or s.expeditor

    print(f"Server: {s.server}:{s.port}  securitate: {s.securitate}  "
          f"autentificare: {'da, ' + s.utilizator if s.utilizator else 'nu'}")
    print(f"De la: {expeditor}  ->  La: {argumente.destinatar}\n")

    mesaj = construieste_mesaj(s, argumente.destinatar, "Probă diagnostic SMTP – Inventare",
                               "Mesaj de probă trimis de scripts/test_smtp.py.", [])
    mesaj.replace_header("From", expeditor)
    mesaj["Date"] = formatdate(localtime=True)
    print(f"Message-ID: {mesaj['Message-ID']}\n")

    try:
        if s.securitate == "ssl":
            smtp = _SMTP_SSL(s.server, s.port, timeout=TIMP_ASTEPTARE, context=ssl.create_default_context())
        else:
            smtp = _SMTP(s.server, s.port, timeout=TIMP_ASTEPTARE)
        smtp.set_debuglevel(1)
        if s.securitate == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if s.utilizator:
            smtp.login(s.utilizator, s.parola)
        refuzate = smtp.sendmail(expeditor, [argumente.destinatar], mesaj.as_string())
        smtp.quit()
    except smtplib.SMTPRecipientsRefused as e:
        print(f"\nDESTINATAR REFUZAT de server: {e.recipients}")
        return 1
    except smtplib.SMTPSenderRefused as e:
        print(f"\nEXPEDITOR REFUZAT de server: {e.smtp_code} {e.smtp_error!r}")
        return 1
    except smtplib.SMTPAuthenticationError as e:
        print(f"\nAUTENTIFICARE EȘUATĂ: {e.smtp_code} {e.smtp_error!r}")
        return 1
    except (smtplib.SMTPException, OSError) as e:
        print(f"\nEROARE: {type(e).__name__}: {e}")
        return 1

    if refuzate:
        print(f"\nAdrese refuzate: {refuzate}")
        return 1
    print("\nServerul a acceptat mesajul (vezi răspunsul 250 de mai sus).")
    print("Dacă nu ajunge: verifică Spam / carantina și jurnalul serverului de e-mail "
          "pentru Message-ID-ul de mai sus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
