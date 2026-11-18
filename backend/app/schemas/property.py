from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class NormalizedPropertyRecord(BaseModel):
    """
    Validated canonical real estate record representation.
    All incoming rows from CSV, Excel, JSON, and PDF must validate against this model.
    """
    company_name: str = Field(..., min_length=1, description="Company / Developer name")
    project_name: str = Field(..., min_length=1, description="Project name")
    city: str = Field(..., min_length=1, description="City")
    state: str = Field(default="Unknown", description="State or province")
    postal_code: str = Field(..., min_length=2, description="Postal / Zip code")
    address_line_1: str = Field(default="Address Pending", description="Street address")

    property_name: str = Field(default="Main Tower", description="Building, Tower, or Phase name")
    unit_number: str = Field(..., min_length=1, description="Unit / Flat / Villa number")
    configuration_type: str = Field(..., min_length=1, description="e.g. 1BHK, 2BHK, 3BHK, Penthouse")
    carpet_area_sqft: Decimal = Field(..., gt=0, description="Carpet area in square feet")
    super_built_up_area_sqft: Optional[Decimal] = Field(None, gt=0)
    floor_number: Optional[int] = Field(None, ge=0)
    facing: Optional[str] = None

    base_price: Decimal = Field(..., ge=0, description="Base selling price")
    total_estimated_price: Optional[Decimal] = Field(None, ge=0)
    currency: str = Field(default="USD")

    availability_status: str = Field(default="available", description="available, reserved, sold, blocked")
    amenities: List[str] = Field(default_factory=list)

    @field_validator("configuration_type")
    @classmethod
    def normalize_config(cls, v: str) -> str:
        clean = v.strip().upper().replace(" ", "")
        # Common synonyms
        if clean in ["1BED", "1BEDROOM", "1-BED", "1-BEDROOM", "1B"]:
            return "1BHK"
        if clean in ["2BED", "2BEDROOM", "2-BED", "2-BEDROOM", "2B"]:
            return "2BHK"
        if clean in ["3BED", "3BEDROOM", "3-BED", "3-BEDROOM", "3B"]:
            return "3BHK"
        if clean in ["4BED", "4BEDROOM", "4-BED", "4-BEDROOM", "4B"]:
            return "4BHK"
        if "STUDIO" in clean:
            return "Studio"
        if "PENTHOUSE" in clean:
            return "Penthouse"
        if "VILLA" in clean:
            return "Villa"
        return clean

    @field_validator("availability_status")
    @classmethod
    def normalize_status(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean in ["available", "open", "vacant", "ready"]:
            return "available"
        if clean in ["reserved", "hold", "pending", "booked"]:
            return "reserved"
        if clean in ["sold", "closed", "purchased"]:
            return "sold"
        if clean in ["blocked", "inactive", "withdrawn"]:
            return "blocked"
        return "available"
