from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inventar.extensions import db


class Sablon(db.Model):
    """Texte editabile de administrator: e-mail, declarații."""

    __tablename__ = "sablon"

    cod: Mapped[str] = mapped_column(String(64), primary_key=True)
    subiect: Mapped[str | None] = mapped_column(String(300))
    corp: Mapped[str] = mapped_column(Text)
