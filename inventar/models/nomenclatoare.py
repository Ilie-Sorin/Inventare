from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inventar.extensions import db

if TYPE_CHECKING:  # import circular la rulare: documente importă modelele de aici
    from inventar.models.documente import Document


class Setare(db.Model):
    __tablename__ = "setare"

    cheie: Mapped[str] = mapped_column(String(64), primary_key=True)
    valoare: Mapped[str] = mapped_column(Text, default="")


class Locatie(db.Model):
    __tablename__ = "locatie"

    id: Mapped[int] = mapped_column(primary_key=True)
    cod: Mapped[str] = mapped_column(String(64), unique=True)
    denumire: Mapped[str] = mapped_column(String(200))
    activ: Mapped[bool] = mapped_column(default=True)


class Activitate(db.Model):
    __tablename__ = "activitate"

    id: Mapped[int] = mapped_column(primary_key=True)
    cod: Mapped[str] = mapped_column(String(64), unique=True)
    denumire: Mapped[str] = mapped_column(String(200))
    activ: Mapped[bool] = mapped_column(default=True)


class Comisie(db.Model):
    __tablename__ = "comisie"
    __table_args__ = (Index("ix_comisie_locatie", "locatie_id", "valabil_de_la"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    locatie_id: Mapped[int] = mapped_column(ForeignKey("locatie.id"))
    valabil_de_la: Mapped[date]
    valabil_pana_la: Mapped[date | None]

    locatie: Mapped[Locatie] = relationship()
    membri: Mapped[list["MembruComisie"]] = relationship(
        back_populates="comisie", order_by="MembruComisie.ordine", cascade="all, delete-orphan"
    )


class MembruComisie(db.Model):
    __tablename__ = "membru_comisie"
    __table_args__ = (CheckConstraint("calitate IN ('PRESEDINTE', 'MEMBRU')", name="calitate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comisie_id: Mapped[int] = mapped_column(ForeignKey("comisie.id"))
    nume: Mapped[str] = mapped_column(String(200))
    calitate: Mapped[str] = mapped_column(String(16))
    ordine: Mapped[int]

    comisie: Mapped[Comisie] = relationship(back_populates="membri")


grup_persoana = Table(
    "grup_persoana",
    db.Model.metadata,
    Column("grup_id", ForeignKey("grup.id"), primary_key=True),
    Column("persoana_id", ForeignKey("persoana.id"), primary_key=True),
)


class Persoana(db.Model):
    """O înregistrare = o gestiune = o listă (vezi §6, §7.3)."""

    __tablename__ = "persoana"

    id: Mapped[int] = mapped_column(primary_key=True)
    nume: Mapped[str] = mapped_column(String(200))
    marca: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(200))
    titular_id: Mapped[int | None] = mapped_column(ForeignKey("persoana.id"))
    activ: Mapped[bool] = mapped_column(default=True)

    titular: Mapped["Persoana | None"] = relationship(remote_side=[id], back_populates="gestiuni_secundare")
    gestiuni_secundare: Mapped[list["Persoana"]] = relationship(back_populates="titular", order_by="Persoana.nume")
    incadrari: Mapped[list["Incadrare"]] = relationship(
        back_populates="persoana", order_by="Incadrare.valabil_de_la"
    )
    grupuri: Mapped[list["Grup"]] = relationship(secondary=grup_persoana, back_populates="persoane")

    @property
    def nume_semnatura(self) -> str:
        # La semnături și la e-mail contează persoana fizică, nu gestiunea.
        return self.titular.nume if self.titular else self.nume


class Incadrare(db.Model):
    __tablename__ = "incadrare"
    __table_args__ = (
        UniqueConstraint("persoana_id", "valabil_de_la"),
        Index("ix_incadrare_persoana_data", "persoana_id", "valabil_de_la"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    persoana_id: Mapped[int] = mapped_column(ForeignKey("persoana.id"))
    locatie_id: Mapped[int] = mapped_column(ForeignKey("locatie.id"))
    activitate_id: Mapped[int] = mapped_column(ForeignKey("activitate.id"))
    valabil_de_la: Mapped[date]
    motiv: Mapped[str | None] = mapped_column(String(500))
    # Documentul INCADRARE care a produs schimbarea (null pentru încadrarea inițială).
    document_id: Mapped[int | None] = mapped_column(ForeignKey("document.id"))

    persoana: Mapped[Persoana] = relationship(back_populates="incadrari")
    locatie: Mapped[Locatie] = relationship()
    activitate: Mapped[Activitate] = relationship()
    document: Mapped["Document | None"] = relationship()


class Grup(db.Model):
    __tablename__ = "grup"

    id: Mapped[int] = mapped_column(primary_key=True)
    denumire: Mapped[str] = mapped_column(String(200), unique=True)

    persoane: Mapped[list[Persoana]] = relationship(
        secondary=grup_persoana, back_populates="grupuri", order_by="Persoana.nume"
    )
