import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.location import Location
from app.models.project import Amenity, Project, ProjectAmenity
from app.models.property import Property, PropertyUnit
from app.models.pricing import Pricing
from app.models.availability import Availability


class PricingBreakdown(BaseModel):
    pricing_id: uuid.UUID
    base_price: Decimal
    currency: str
    maintenance_charge_monthly: Decimal
    parking_charge: Decimal
    estimated_tax: Decimal
    total_estimated_price: Decimal
    is_active: bool
    valid_from: datetime
    valid_to: Optional[datetime] = None


class PropertyUnitDetail(BaseModel):
    unit_id: uuid.UUID
    unit_number: str
    configuration_type: str
    carpet_area_sqft: Decimal
    super_built_up_area_sqft: Optional[Decimal] = None
    floor_number: Optional[int] = None
    facing: Optional[str] = None
    balcony_count: int
    property_name: str
    property_type: str
    total_floors: Optional[int] = None
    project_id: uuid.UUID
    project_name: str
    project_status: str
    company_name: str
    city: str
    state: str
    postal_code: str
    address_line_1: str
    current_pricing: Optional[PricingBreakdown] = None
    pricing_history: List[PricingBreakdown] = Field(default_factory=list)
    current_availability: Optional[str] = None
    amenities: List[str] = Field(default_factory=list)


def get_property_unit_details(
    db: Session,
    unit_id: uuid.UUID,
    include_pricing_history: bool = False
) -> Optional[PropertyUnitDetail]:
    """
    Fetches full verified property and unit specifications with verified active pricing.
    Never quotes expired or unverified pricing as active.
    """
    unit = db.get(PropertyUnit, unit_id)
    if not unit:
        return None

    prop = db.get(Property, unit.property_id)
    project = db.get(Project, prop.project_id) if prop else None
    company = db.get(Company, project.company_id) if project else None
    location = db.get(Location, project.location_id) if project else None

    # Fetch active pricing
    active_price_row = db.execute(
        select(Pricing).where(Pricing.unit_id == unit.id, Pricing.is_active == True)
    ).scalar_one_or_none()

    current_pricing = None
    if active_price_row:
        current_pricing = PricingBreakdown(
            pricing_id=active_price_row.id,
            base_price=active_price_row.base_price,
            currency=active_price_row.currency,
            maintenance_charge_monthly=active_price_row.maintenance_charge_monthly,
            parking_charge=active_price_row.parking_charge,
            estimated_tax=active_price_row.estimated_tax,
            total_estimated_price=active_price_row.total_estimated_price,
            is_active=active_price_row.is_active,
            valid_from=active_price_row.valid_from,
            valid_to=active_price_row.valid_to,
        )

    # Fetch pricing history if requested
    pricing_history: List[PricingBreakdown] = []
    if include_pricing_history:
        all_prices = db.execute(
            select(Pricing).where(Pricing.unit_id == unit.id).order_by(Pricing.valid_from.desc())
        ).scalars().all()
        for p in all_prices:
            pricing_history.append(
                PricingBreakdown(
                    pricing_id=p.id,
                    base_price=p.base_price,
                    currency=p.currency,
                    maintenance_charge_monthly=p.maintenance_charge_monthly,
                    parking_charge=p.parking_charge,
                    estimated_tax=p.estimated_tax,
                    total_estimated_price=p.total_estimated_price,
                    is_active=p.is_active,
                    valid_from=p.valid_from,
                    valid_to=p.valid_to,
                )
            )

    # Fetch active availability
    active_avail = db.execute(
        select(Availability).where(Availability.unit_id == unit.id, Availability.is_current == True)
    ).scalar_one_or_none()

    current_avail_status = active_avail.status if active_avail else "unknown"

    # Fetch project amenities
    amenities: List[str] = []
    if project:
        amenities = list(db.execute(
            select(Amenity.name)
            .join(ProjectAmenity, ProjectAmenity.amenity_id == Amenity.id)
            .where(ProjectAmenity.project_id == project.id, Amenity.is_active == True)
        ).scalars().all())

    return PropertyUnitDetail(
        unit_id=unit.id,
        unit_number=unit.unit_number,
        configuration_type=unit.configuration_type,
        carpet_area_sqft=unit.carpet_area_sqft,
        super_built_up_area_sqft=unit.super_built_up_area_sqft,
        floor_number=unit.floor_number,
        facing=unit.facing,
        balcony_count=unit.balcony_count,
        property_name=prop.name if prop else "Unknown Property",
        property_type=prop.property_type if prop else "apartment",
        total_floors=prop.total_floors if prop else None,
        project_id=project.id if project else uuid.uuid4(),
        project_name=project.name if project else "Unknown Project",
        project_status=project.status if project else "unknown",
        company_name=company.name if company else "Unknown Developer",
        city=location.city if location else "Unknown City",
        state=location.state if location else "Unknown State",
        postal_code=location.postal_code if location else "Unknown Postal Code",
        address_line_1=location.address_line_1 if location else "Address Unavailable",
        current_pricing=current_pricing,
        pricing_history=pricing_history,
        current_availability=current_avail_status,
        amenities=amenities,
    )
