from datetime import datetime

from sqlalchemy import DDL, ForeignKey, Index, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from inventar.extensions import db


class Jurnal(db.Model):
    __tablename__ = "jurnal"
    __table_args__ = (Index("ix_jurnal_la", "la"), Index("ix_jurnal_actiune", "actiune"))

    id: Mapped[int] = mapped_column(primary_key=True)
    la: Mapped[datetime]
    utilizator_id: Mapped[int | None] = mapped_column(ForeignKey("utilizator.id"))
    # Numele se copiază: rămâne lizibil chiar dacă utilizatorul e redenumit,
    # iar la autentificările eșuate poate fi un nume inexistent.
    username: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(45))
    actiune: Mapped[str] = mapped_column(String(64))
    obiect_tip: Mapped[str | None] = mapped_column(String(32))
    obiect_id: Mapped[int | None]
    detalii_json: Mapped[str] = mapped_column(Text, default="{}")
    rezultat: Mapped[str] = mapped_column(String(16), default="OK")


# Jurnalul e append-only și la nivel de bază de date, nu doar prin convenție
# în cod: nicio actualizare sau ștergere nu poate trece, nici din greșeală.
TRIGGERE_JURNAL = (
    "CREATE TRIGGER jurnal_fara_update BEFORE UPDATE ON jurnal "
    "BEGIN SELECT RAISE(ABORT, 'jurnalul nu se modifică'); END",
    "CREATE TRIGGER jurnal_fara_delete BEFORE DELETE ON jurnal "
    "BEGIN SELECT RAISE(ABORT, 'jurnalul nu se șterge'); END",
)

for _sql in TRIGGERE_JURNAL:
    event.listen(Jurnal.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))
