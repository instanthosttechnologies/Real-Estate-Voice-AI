import uuid
from datetime import date, datetime, timezone
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.property import PropertyUnit
from app.models.availability import Availability


class AvailabilityStatusReport(BaseModel):
    unit_id: uuid.UUID
    unit_number: str
    status: str  # 'available', 'reserved', 'sold', 'blocked', 'unknown'
    is_bookable: bool
    available_from: Optional[date] = None
    hold_expires_at: Optional[datetime] = None
    remarks: str


def check_unit_availability(
    db: Session,
    unit_id: uuid.UUID
) -> AvailabilityStatusReport:
    """
    Checks the active, verified availability status of a property unit.
    Never assumes availability.
    """
    unit = db.get(PropertyUnit, unit_id)
    if not unit:
        return AvailabilityStatusReport(
            unit_id=unit_id,
            unit_number="N/A",
            status="unknown",
            is_bookable=False,
            remarks="Unit does not exist in inventory records.",
        )

    avail = db.execute(
        select(Availability).where(
            Availability.unit_id == unit.id,
            Availability.is_current == True
        )
    ).scalar_one_or_none()

    if not avail:
        return AvailabilityStatusReport(
            unit_id=unit.id,
            unit_number=unit.unit_number,
            status="unknown",
            is_bookable=False,
            remarks="No active availability record found for this unit. Verification required.",
        )

    normalized_status = avail.status.lower()

    if normalized_status == "available":
        return AvailabilityStatusReport(
            unit_id=unit.id,
            unit_number=unit.unit_number,
            status="available",
            is_bookable=True,
            available_from=avail.available_from,
            remarks="Unit is currently available for site visits and reservation.",
        )
    elif normalized_status == "reserved":
        now = datetime.now(timezone.utc)
        if avail.hold_expires_at and avail.hold_expires_at < now:
            # Hold has lapsed
            return AvailabilityStatusReport(
                unit_id=unit.id,
                unit_number=unit.unit_number,
                status="reserved",
                is_bookable=False,
                hold_expires_at=avail.hold_expires_at,
                remarks="Unit reservation hold is currently under expiration review.",
            )
        return AvailabilityStatusReport(
            unit_id=unit.id,
            unit_number=unit.unit_number,
            status="reserved",
            is_bookable=False,
            hold_expires_at=avail.hold_expires_at,
            remarks="Unit is currently on hold / reserved by another prospective buyer.",
        )
    elif normalized_status == "sold":
        return AvailabilityStatusReport(
            unit_id=unit.id,
            unit_number=unit.unit_number,
            status="sold",
            is_bookable=False,
            remarks="Unit has been sold and is no longer available on the market.",
        )
    elif normalized_status == "blocked":
        return AvailabilityStatusReport(
            unit_id=unit.id,
            unit_number=unit.unit_number,
            status="blocked",
            is_bookable=False,
            remarks="Unit is temporarily blocked or withdrawn by the developer.",
        )
    else:
        return AvailabilityStatusReport(
            unit_id=unit.id,
            unit_number=unit.unit_number,
            status="unknown",
            is_bookable=False,
            remarks=f"Unrecognized availability status: {avail.status}.",
        )
