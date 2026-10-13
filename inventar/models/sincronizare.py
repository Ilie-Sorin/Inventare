from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inventar.extensions import db
from inventar.models.utilizator import Utilizator


class Sincronizare(db.Model):
    """O încărcare a exportului contabil: analiza se salvează, aplicarea cere confirmare (§9.4)."""

    __tablename__ = "sincronizare"
    __table_args__ = (CheckConstraint("stare IN ('INCARCATA', 'APLICATA', 'ABANDONATA')", name="stare"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # JSON: [{"original", "salvat"}]; fișierele stau în instance/sincronizari/<director>/
    fisier: Mapped[str] = mapped_column(Text)
    director: Mapped[str] = mapped_column(String(64))
    incarcat_de: Mapped[int | None] = mapped_column(ForeignKey("utilizator.id"))
    incarcat_la: Mapped[datetime]
    aplicat_la: Mapped[datetime | None]
    stare: Mapped[str] = mapped_column(String(16), default="INCARCATA")
    rezumat_json: Mapped[str] = mapped_column(Text, default="{}")

    utilizator: Mapped[Utilizator | None] = relationship()
    diferente: Mapped[list["SincronizareDiferenta"]] = relationship(
        back_populates="sincronizare", order_by="SincronizareDiferenta.id", cascade="all, delete-orphan"
    )


class SincronizareDiferenta(db.Model):
    __tablename__ = "sincronizare_diferenta"
    __table_args__ = (Index("ix_sincronizare_diferenta_sinc", "sincronizare_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sincronizare_id: Mapped[int] = mapped_column(ForeignKey("sincronizare.id"))
    tip: Mapped[str] = mapped_column(String(16))
    nr_inventar: Mapped[str] = mapped_column(String(32))
    bun_id: Mapped[int | None] = mapped_column(ForeignKey("bun.id"))
    detalii_json: Mapped[str] = mapped_column(Text, default="{}")
    # APLICAT | IGNORAT, după confirmare; null cât sincronizarea e doar încărcată.
    actiune: Mapped[str | None] = mapped_column(String(16))
    rezolvat: Mapped[bool] = mapped_column(default=False)

    sincronizare: Mapped[Sincronizare] = relationship(back_populates="diferente")
