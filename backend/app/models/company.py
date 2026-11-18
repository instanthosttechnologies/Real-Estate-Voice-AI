import uuid
from typing import List
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin
from app.db.types import GUID


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    registration_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=True)

    # Relationships
    projects: Mapped[List["Project"]] = relationship("Project", back_populates="company")
