import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.location import Location
from app.models.project import Amenity, Project, ProjectAmenity
from app.models.property import Property, PropertyUnit
from app.models.pricing import Pricing
from app.models.availability import Availability


class PropertySearchCriteria(BaseModel):
    city: Optional[str] = None
    location_query: Optional[str] = None
    company_name: Optional[str] = None
    project_name: Optional[str] = None
    property_type: Optional[str] = None
    configuration_type: Optional[str] = None
    min_budget: Optional[Decimal] = Field(None, ge=0)
    max_budget: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = Field(None, description="ISO 4217 currency code e.g. USD, INR, EUR, AED, GBP")
    min_carpet_area: Optional[Decimal] = Field(None, gt=0)
    max_carpet_area: Optional[Decimal] = Field(None, gt=0)
    required_amenities: Optional[List[str]] = Field(default_factory=list)
    availability_status: Optional[str] = "available"
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class PropertySearchResultItem(BaseModel):
    unit_id: uuid.UUID
    property_id: uuid.UUID
    project_id: uuid.UUID
    unit_number: str
    property_name: str
    property_type: str
    project_name: str
    company_name: str
    city: str
    state: str
    postal_code: str
    address_line_1: str
    configuration_type: str
    carpet_area_sqft: Decimal
    floor_number: Optional[int] = None
    facing: Optional[str] = None
    base_price: Decimal
    total_estimated_price: Decimal
    currency: str
    availability_status: str
    amenities: List[str] = Field(default_factory=list)


def search_properties(
    db: Session,
    criteria: PropertySearchCriteria
) -> List[PropertySearchResultItem]:
    """
    Executes a deterministic, multi-criteria parameterized query across normalized real estate entities.
    Returns only genuine database records. Never fabricates records.
    """
    stmt = (
        select(
            PropertyUnit.id.label("unit_id"),
            Property.id.label("property_id"),
            Project.id.label("project_id"),
            PropertyUnit.unit_number,
            Property.name.label("property_name"),
            Property.property_type,
            Project.name.label("project_name"),
            Company.name.label("company_name"),
            Location.city,
            Location.state,
            Location.postal_code,
            Location.address_line_1,
            PropertyUnit.configuration_type,
            PropertyUnit.carpet_area_sqft,
            PropertyUnit.floor_number,
            PropertyUnit.facing,
            Pricing.base_price,
            Pricing.total_estimated_price,
            Pricing.currency,
            Availability.status.label("availability_status"),
        )
        .join(Property, PropertyUnit.property_id == Property.id)
        .join(Project, Property.project_id == Project.id)
        .join(Company, Project.company_id == Company.id)
        .join(Location, Project.location_id == Location.id)
        .join(Pricing, (Pricing.unit_id == PropertyUnit.id) & (Pricing.is_active == True))
        .join(Availability, (Availability.unit_id == PropertyUnit.id) & (Availability.is_current == True))
    )

    # 1. City filter
    if criteria.city:
        stmt = stmt.where(func.lower(Location.city) == criteria.city.strip().lower())

    # 2. Location keyword filter (address, landmark, postal code)
    if criteria.location_query:
        query_pattern = f"%{criteria.location_query.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Location.address_line_1).like(query_pattern) |
            func.lower(Location.city).like(query_pattern) |
            func.lower(Location.landmark).like(query_pattern) |
            func.lower(Location.postal_code).like(query_pattern)
        )

    # 3. Company filter
    if criteria.company_name:
        stmt = stmt.where(func.lower(Company.name).like(f"%{criteria.company_name.strip().lower()}%"))

    # 4. Project filter
    if criteria.project_name:
        stmt = stmt.where(func.lower(Project.name).like(f"%{criteria.project_name.strip().lower()}%"))

    # 5. Property type filter
    if criteria.property_type:
        stmt = stmt.where(func.lower(Property.property_type) == criteria.property_type.strip().lower())

    # 6. Configuration type (BHK) filter
    if criteria.configuration_type:
        clean_config = criteria.configuration_type.strip().upper().replace(" ", "")
        stmt = stmt.where(func.upper(PropertyUnit.configuration_type) == clean_config)

    # 7. Budget range & currency filter
    if criteria.currency:
        stmt = stmt.where(func.upper(Pricing.currency) == criteria.currency.strip().upper())
    if criteria.min_budget is not None:
        stmt = stmt.where(Pricing.base_price >= criteria.min_budget)
    if criteria.max_budget is not None:
        stmt = stmt.where(Pricing.base_price <= criteria.max_budget)

    # 8. Carpet area range filter
    if criteria.min_carpet_area is not None:
        stmt = stmt.where(PropertyUnit.carpet_area_sqft >= criteria.min_carpet_area)
    if criteria.max_carpet_area is not None:
        stmt = stmt.where(PropertyUnit.carpet_area_sqft <= criteria.max_carpet_area)

    # 9. Availability status filter
    if criteria.availability_status:
        stmt = stmt.where(func.lower(Availability.status) == criteria.availability_status.strip().lower())

    # 10. Required amenities filter
    if criteria.required_amenities:
        for amen in criteria.required_amenities:
            clean_amen = amen.strip().lower()
            stmt = stmt.where(
                Project.id.in_(
                    select(ProjectAmenity.project_id)
                    .join(Amenity, ProjectAmenity.amenity_id == Amenity.id)
                    .where(func.lower(Amenity.name) == clean_amen)
                )
            )

    # Ordering & Pagination
    stmt = stmt.order_by(Pricing.base_price.asc()).offset(criteria.offset).limit(criteria.limit)

    rows = db.execute(stmt).all()
    results: List[PropertySearchResultItem] = []

    for r in rows:
        # Fetch project amenities
        amenities_res = db.execute(
            select(Amenity.name)
            .join(ProjectAmenity, ProjectAmenity.amenity_id == Amenity.id)
            .where(ProjectAmenity.project_id == r.project_id)
            .where(Amenity.is_active == True)
        ).scalars().all()

        results.append(
            PropertySearchResultItem(
                unit_id=r.unit_id,
                property_id=r.property_id,
                project_id=r.project_id,
                unit_number=r.unit_number,
                property_name=r.property_name,
                property_type=r.property_type,
                project_name=r.project_name,
                company_name=r.company_name,
                city=r.city,
                state=r.state,
                postal_code=r.postal_code,
                address_line_1=r.address_line_1,
                configuration_type=r.configuration_type,
                carpet_area_sqft=r.carpet_area_sqft,
                floor_number=r.floor_number,
                facing=r.facing,
                base_price=r.base_price,
                total_estimated_price=r.total_estimated_price,
                currency=r.currency,
                availability_status=r.availability_status,
                amenities=list(amenities_res),
            )
        )

    return results
