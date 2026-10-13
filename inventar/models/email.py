from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inventar.extensions import db
from inventar.models.nomenclatoare import Persoana


class TrimitereEmail(db.Model):
    """Un destinatar dintr-o trimitere (lot); starea se salvează pe fiecare, ca retrimiterea
    să poată merge doar la cei cu eroare."""

    __tablename__ = "trimitere_email"
    __table_args__ = (
        CheckConstraint("stare IN ('IN_ASTEPTARE', 'TRIMIS', 'EROARE')", name="stare"),
        Index("ix_trimitere_email_lot", "lot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lot: Mapped[str] = mapped_column(String(32))
    inventar_id: Mapped[int] = mapped_column(ForeignKey("inventar.id"))
    titular_id: Mapped[int] = mapped_column(ForeignKey("persoana.id"))
    adresa: Mapped[str] = mapped_column(String(200))
    stare: Mapped[str] = mapped_column(String(16), default="IN_ASTEPTARE")
    eroare: Mapped[str | None] = mapped_column(String(1000))
    creat_la: Mapped[datetime]
    trimis_la: Mapped[datetime | None]
    # [{"persoana_id", "categorie", "fisier"}]: atașamentele se generează la trimitere, din instantaneu.
    atasamente_json: Mapped[str] = mapped_column(Text, default="[]")
    subiect: Mapped[str] = mapped_column(String(300), default="")
    corp: Mapped[str] = mapped_column(Text, default="")

    titular: Mapped[Persoana] = relationship()
