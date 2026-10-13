from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inventar.extensions import db
from inventar.models.utilizator import Utilizator

STARI_INVENTAR = ("GENERAT", "NEACTUALIZAT", "BLOCAT")


class Inventar(db.Model):
    """Instantaneul situației la o dată; listele se tipăresc numai de aici (§7.6)."""

    __tablename__ = "inventar"
    __table_args__ = (
        CheckConstraint("stare IN ('GENERAT', 'NEACTUALIZAT', 'BLOCAT')", name="stare"),
        # La aceeași dată și același perimetru e permis un singur inventar.
        UniqueConstraint("data", "perimetru_json", name="uq_inventar_data_perimetru"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[date]
    perimetru_json: Mapped[str] = mapped_column(Text)
    stare: Mapped[str] = mapped_column(String(16))
    generat_de: Mapped[int | None] = mapped_column(ForeignKey("utilizator.id"))
    generat_la: Mapped[datetime]
    nr_linii: Mapped[int]
    motiv_deblocare: Mapped[str | None] = mapped_column(String(1000))

    utilizator: Mapped[Utilizator | None] = relationship()
    comisii: Mapped[list["InventarComisie"]] = relationship(
        back_populates="inventar", order_by="InventarComisie.locatie", cascade="all, delete-orphan"
    )


class InventarLinie(db.Model):
    """Copie a tuturor câmpurilor necesare tipăririi, ca lista să nu se schimbe după generare."""

    __tablename__ = "inventar_linie"
    __table_args__ = (Index("ix_inventar_linie_inventar", "inventar_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    inventar_id: Mapped[int] = mapped_column(ForeignKey("inventar.id"))
    bun_id: Mapped[int] = mapped_column(ForeignKey("bun.id"))
    nr_inventar: Mapped[str] = mapped_column(String(32))
    nr_inventar_vechi: Mapped[str | None] = mapped_column(String(32))
    denumire: Mapped[str] = mapped_column(String(500))
    um: Mapped[str] = mapped_column(String(16))
    serie: Mapped[str | None] = mapped_column(String(200))
    categorie: Mapped[str] = mapped_column(String(2))
    cont: Mapped[str] = mapped_column(String(32))
    cont_sintetic: Mapped[str] = mapped_column(String(3))
    pret: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    data_amortizare_integrala: Mapped[date | None]
    persoana_id: Mapped[int] = mapped_column(ForeignKey("persoana.id"))
    gestiune: Mapped[str] = mapped_column(String(200))
    # Persoana fizică: titularul gestiunii secundare sau gestiunea însăși. La ea merg
    # semnătura de pe listă și e-mailul.
    titular_id: Mapped[int] = mapped_column(ForeignKey("persoana.id"))
    titular: Mapped[str] = mapped_column(String(200))
    locatie_id: Mapped[int] = mapped_column(ForeignKey("locatie.id"))
    locatie: Mapped[str] = mapped_column(String(200))
    activitate_id: Mapped[int] = mapped_column(ForeignKey("activitate.id"))
    activitate: Mapped[str] = mapped_column(String(200))


class InventarComisie(db.Model):
    __tablename__ = "inventar_comisie"

    id: Mapped[int] = mapped_column(primary_key=True)
    inventar_id: Mapped[int] = mapped_column(ForeignKey("inventar.id"))
    locatie_id: Mapped[int] = mapped_column(ForeignKey("locatie.id"))
    locatie: Mapped[str] = mapped_column(String(200))
    membri_json: Mapped[str] = mapped_column(Text, default="[]")

    inventar: Mapped[Inventar] = relationship(back_populates="comisii")
