from flask_login import UserMixin
from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inventar.extensions import db
from inventar.models.nomenclatoare import Persoana

ROLURI = ("ADMIN", "OPERATOR", "CONSULTARE")


class Utilizator(UserMixin, db.Model):
    __tablename__ = "utilizator"
    __table_args__ = (CheckConstraint("rol IN ('ADMIN', 'OPERATOR', 'CONSULTARE')", name="rol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    parola_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(16))
    activ: Mapped[bool] = mapped_column(default=True)
    persoana_id: Mapped[int | None] = mapped_column(ForeignKey("persoana.id"))

    persoana: Mapped[Persoana | None] = relationship()

    @property
    def is_active(self) -> bool:  # Flask-Login refuză automat conturile dezactivate
        return self.activ
