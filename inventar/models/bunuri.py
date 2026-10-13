from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inventar.extensions import db

CATEGORII = ("MF", "OI")


class Cont(db.Model):
    __tablename__ = "cont"
    __table_args__ = (CheckConstraint("categorie IN ('MF', 'OI')", name="categorie"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    simbol: Mapped[str] = mapped_column(String(32), unique=True)
    sintetic: Mapped[str] = mapped_column(String(3))
    categorie: Mapped[str] = mapped_column(String(2))
    denumire: Mapped[str | None] = mapped_column(String(200))


class Bun(db.Model):
    """Datele bunului vin numai din exportul contabil și nu se editează în aplicație (§7.1)."""

    __tablename__ = "bun"
    __table_args__ = (CheckConstraint("categorie IN ('MF', 'OI')", name="categorie"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nr_inventar: Mapped[str] = mapped_column(String(32), unique=True)
    nr_inventar_vechi: Mapped[str | None] = mapped_column(String(32))
    categorie: Mapped[str] = mapped_column(String(2))
    cont_id: Mapped[int] = mapped_column(ForeignKey("cont.id"))
    denumire: Mapped[str] = mapped_column(String(500))
    um: Mapped[str] = mapped_column(String(16))
    serie: Mapped[str | None] = mapped_column(String(200))
    pret: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    data_pif: Mapped[date | None]
    data_amortizare_integrala: Mapped[date | None]
    cod_clasificare: Mapped[str | None] = mapped_column(String(32))
    durata_normala: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    nr_doc_intrare: Mapped[str | None] = mapped_column(String(64))
    data_doc_intrare: Mapped[date | None]
    nr_doc_casare: Mapped[str | None] = mapped_column(String(64))
    data_casare: Mapped[date | None]
    explicatie_casare: Mapped[str | None] = mapped_column(String(500))
    mentiuni: Mapped[str | None] = mapped_column(String(1000))
    prezent_in_export: Mapped[bool] = mapped_column(default=True)
    actualizat_la: Mapped[datetime]

    cont: Mapped[Cont] = relationship()
