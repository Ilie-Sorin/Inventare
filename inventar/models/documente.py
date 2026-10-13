from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inventar.extensions import db
from inventar.models.bunuri import Bun
from inventar.models.nomenclatoare import Persoana

TIPURI_DOCUMENT = ("INITIAL", "INTRARE", "IESIRE", "TRANSFER", "INCADRARE")
STARI_DOCUMENT = ("CIORNA", "VALIDAT", "ANULAT")


class Document(db.Model):
    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint("tip IN ('INITIAL', 'INTRARE', 'IESIRE', 'TRANSFER', 'INCADRARE')", name="tip"),
        CheckConstraint("stare IN ('CIORNA', 'VALIDAT', 'ANULAT')", name="stare"),
        Index("ix_document_data_stare", "data", "stare"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tip: Mapped[str] = mapped_column(String(16))
    serie: Mapped[str | None] = mapped_column(String(16))
    numar: Mapped[str] = mapped_column(String(32))
    data: Mapped[date]
    explicatie: Mapped[str | None] = mapped_column(String(1000))
    motiv_iesire: Mapped[str | None] = mapped_column(String(200))
    stare: Mapped[str] = mapped_column(String(16), default="CIORNA")
    creat_de: Mapped[int | None] = mapped_column(ForeignKey("utilizator.id"))
    creat_la: Mapped[datetime]
    validat_de: Mapped[int | None] = mapped_column(ForeignKey("utilizator.id"))
    validat_la: Mapped[datetime | None]
    anulat_de: Mapped[int | None] = mapped_column(ForeignKey("utilizator.id"))
    anulat_la: Mapped[datetime | None]
    motiv_anulare: Mapped[str | None] = mapped_column(String(1000))

    linii: Mapped[list["LinieDocument"]] = relationship(back_populates="document", order_by="LinieDocument.id")


class LinieDocument(db.Model):
    __tablename__ = "linie_document"
    __table_args__ = (Index("ix_linie_document_bun", "bun_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"))
    bun_id: Mapped[int] = mapped_column(ForeignKey("bun.id"))
    persoana_de_la_id: Mapped[int | None] = mapped_column(ForeignKey("persoana.id"))
    persoana_la_id: Mapped[int | None] = mapped_column(ForeignKey("persoana.id"))

    document: Mapped[Document] = relationship(back_populates="linii")
    bun: Mapped[Bun] = relationship()
    persoana_de_la: Mapped[Persoana | None] = relationship(foreign_keys=[persoana_de_la_id])
    persoana_la: Mapped[Persoana | None] = relationship(foreign_keys=[persoana_la_id])
