from sqlalchemy import BigInteger, Column, ForeignKey, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped

from app.database import Base


class UserRole(Base):
    __tablename__ = "sys_user_role"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)  # type: ignore[name-defined]
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # type: ignore[name-defined]
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # type: ignore[name-defined]

    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uk_user_role"),)