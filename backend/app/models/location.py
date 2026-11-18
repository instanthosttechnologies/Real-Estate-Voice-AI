import uuid
from datetime import datetime

from app.db.base import Base, utc_now
from app.db.types import GUID
from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)

    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)

    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)

    city: Mapped[str] = mapped_column(String(100), index=True, nullable=False)

    state: Mapped[str] = mapped_column(String(100), index=True, nullable=False)

    postal_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    country: Mapped[str] = mapped_column(String(100), default="USA", nullable=False)

    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)

    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)

    landmark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="location"
    )
