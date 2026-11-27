import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.lead import Lead
from app.models.customer import Customer
from app.models.pricing import Pricing
from app.models.audit_log import AuditLog
from app.models.appointment import Appointment
from app.models.property import PropertyUnit, Property
from app.models.project import Project
from app.models.site_visit import SiteVisit
from app.schemas.agent_tools import (
    AgentToolResponse,
    BookSiteVisitToolInput,
    CancelSiteVisitToolInput,
    CheckPropertyAvailabilityToolInput,
    CheckVisitSlotsToolInput,
    ComparePropertiesToolInput,
    CreateLeadToolInput,
    ExtractRequirementsToolInput,
    GetPropertyDetailsToolInput,
    GetPropertyPriceToolInput,
    RescheduleSiteVisitToolInput,
    SearchPropertiesToolInput,
    ShowPropertyImagesToolInput,
    GetDatasetSummaryToolInput,
    QueryActiveDatasetToolInput,
    QueryBusinessDatasetToolInput,
    TransferToHumanToolInput,
    UpdateLeadToolInput,
    CalculateLeadPriorityToolInput,
)
from app.services.real_estate.search import PropertySearchCriteria, search_properties
from app.services.real_estate.matcher import CustomerPreferences, intelligent_property_search
from app.services.real_estate.details import get_property_unit_details
from app.services.real_estate.availability import check_unit_availability
from app.services.real_estate.requirements import extract_requirements_from_text
from app.services.real_estate.priority import calculate_lead_priority
from app.services.real_estate.leads import (
    CreateLeadInput,
    UpdateLeadInput,
    create_customer_lead,
    update_customer_lead,
)
from app.services.real_estate.site_visits import (
    BookVisitInput,
    RescheduleVisitInput,
    book_site_visit,
    cancel_site_visit,
    get_available_visit_slots,
    reschedule_site_visit,
)
from app.services.dataset.manager import get_active_dataset
from app.services.dataset.retrieval import query_dynamic_dataset, query_universal_dataset
from app.core.config import settings
from app.services.real_estate.demo_dataset import DemoDatasetService
import re


def tool_search_properties(db: Session, args: SearchPropertiesToolInput) -> AgentToolResponse:
    # 1. Check if an active dynamic dataset is configured in the database
    active_ds = get_active_dataset(db)
    if active_ds:
        query_terms = " ".join([
            v for v in [args.project_name, args.company_name, args.city, args.location_query, args.configuration_type, args.property_type]
            if v
        ])
        if not query_terms and args.required_amenities:
            query_terms = " ".join(args.required_amenities)
        if query_terms:
            ds_res = query_dynamic_dataset(db, query_terms, limit=args.limit)
            if ds_res.get("found") and ds_res.get("records"):
                return AgentToolResponse(
                    tool_name="search_properties",
                    success=True,
                    data={
                        "dataset_grounded": True,
                        "dataset_name": ds_res["dataset_name"],
                        "dataset_version": ds_res["dataset_version"],
                        "total_exact_matches": ds_res["returned_matches"],
                        "exact_matches": ds_res["records"],
                        "voice_grounding": ds_res["voice_grounding"],
                    },
                    anti_hallucination_guidance=(
                        "State only the properties returned in exact_matches and use the voice_grounding summary. "
                        "Never fabricate unlisted projects, prices, or configurations."
                    ),
                )

    has_db_units = False
    if db is not None:
        try:
            has_db_units = db.execute(select(PropertyUnit).limit(1)).scalar_one_or_none() is not None
        except Exception:
            pass

    # 2. Check if DEMO_DATASET_MODE is active (when authentic PropertyUnits are not populated)
    if not has_db_units and getattr(settings, "DEMO_DATASET_MODE", False):
        demo_svc = DemoDatasetService.get_instance()
        bhk_val = None
        if args.configuration_type:
            m = re.search(r"(\d+)", str(args.configuration_type))
            if m:
                bhk_val = int(m.group(1))

        demo_matches = demo_svc.search_properties(
            city=args.city,
            locality=args.location_query,
            project_name=args.project_name,
            developer=args.company_name,
            property_type=args.property_type,
            bhk=bhk_val,
            min_budget=float(args.min_budget) if args.min_budget else None,
            max_budget=float(args.max_budget) if args.max_budget else None,
            amenities=args.required_amenities,
            limit=args.limit,
        )
        if demo_matches:
            voice_lines = []
            for p in demo_matches[:3]:
                voice_lines.append(
                    f"{p['project_name']} by {p['developer_name']} in {p['locality']}, {p['city']}. "
                    f"Amenities include {str(p['amenities'])[:80]}. {p['spoken_price_script']}"
                )
            return AgentToolResponse(
                tool_name="search_properties",
                success=True,
                data={
                    "is_demo_mode": True,
                    "dataset_grounded": True,
                    "dataset_name": "BrainMagic_RealEstate_v10_Demo",
                    "total_matches": len(demo_matches),
                    "total_exact_matches": len(demo_matches),
                    "exact_matches": demo_matches,
                    "properties": demo_matches,
                    "voice_grounding": " ".join(voice_lines),
                },
                anti_hallucination_guidance=(
                    "For this demo, state estimated prices using the format: "
                    "'For this demo, the estimated price is around [price range]. The actual selling price may vary.' "
                    "Never present demo prices as confirmed seller quotations."
                ),
            )
    active_ds = get_active_dataset(db)
    if active_ds:
        query_terms = " ".join([
            v for v in [args.project_name, args.company_name, args.city, args.location_query, args.configuration_type, args.property_type]
            if v
        ])
        if not query_terms and args.required_amenities:
            query_terms = " ".join(args.required_amenities)
        if query_terms:
            ds_res = query_dynamic_dataset(db, query_terms, limit=args.limit)
            if ds_res.get("found") and ds_res.get("records"):
                return AgentToolResponse(
                    tool_name="search_properties",
                    success=True,
                    data={
                        "dataset_grounded": True,
                        "dataset_name": ds_res["dataset_name"],
                        "dataset_version": ds_res["dataset_version"],
                        "total_exact_matches": ds_res["returned_matches"],
                        "exact_matches": ds_res["records"],
                        "voice_grounding": ds_res["voice_grounding"],
                    },
                    anti_hallucination_guidance=(
                        "State only the properties returned in exact_matches and use the voice_grounding summary. "
                        "Never fabricate unlisted projects, prices, or configurations."
                    ),
                )

    criteria = PropertySearchCriteria(
        city=args.city,
        location_query=args.location_query,
        company_name=args.company_name,
        project_name=args.project_name,
        property_type=args.property_type,
        configuration_type=args.configuration_type,
        min_budget=args.min_budget,
        max_budget=args.max_budget,
        currency=args.currency,
        min_carpet_area=args.min_carpet_area,
        max_carpet_area=args.max_carpet_area,
        required_amenities=args.required_amenities,
        availability_status=args.availability_status,
        limit=args.limit,
    )
    prefs = CustomerPreferences(
        preferred_city=args.city,
        preferred_location=args.location_query,
        preferred_config=args.configuration_type,
        budget_min=args.min_budget,
        budget_max=args.max_budget,
        preferred_currency=args.currency,
        desired_amenities=args.required_amenities or [],
    )
    search_data = intelligent_property_search(db, criteria, prefs)

    guidance = (
        "Quote only properties present in 'exact_matches' or 'recommended_alternatives'. "
        "If total_exact_matches > 0, present the exact matches first. "
        "If total_exact_matches is 0 and recommended_alternatives exist, do NOT present them as exact matches; "
        "politely inform the customer that no exact match was found and ask if they would like to review the suggested alternatives. "
        "Never invent property details, prices, or amenities."
    )

    return AgentToolResponse(
        tool_name="search_properties",
        success=True,
        data=search_data,
        anti_hallucination_guidance=guidance,
    )


def tool_compare_properties(db: Session, args: ComparePropertiesToolInput) -> AgentToolResponse:
    """
    Compares 2 to 5 property units side-by-side. Supports both Excel Demo mode
    and authentic database records.
    """
    unit_ids = args.unit_ids
    if len(unit_ids) < 2:
        return AgentToolResponse(
            tool_name="compare_properties",
            success=False,
            error_message="At least 2 property unit IDs are required for a side-by-side comparison.",
        )

    # Demo Mode Check
    if getattr(settings, "DEMO_DATASET_MODE", False):
        demo_svc = DemoDatasetService.get_instance()
        comp_res = demo_svc.compare_properties([str(u) for u in unit_ids])
        if comp_res.get("success"):
            return AgentToolResponse(
                tool_name="compare_properties",
                success=True,
                data=comp_res,
                anti_hallucination_guidance=(
                    "Compare only the exact values provided in the comparison data. "
                    "Remind the customer that demo prices are approximate."
                ),
            )

    comparison_items: List[Dict[str, Any]] = []
    missing_ids: List[str] = []

    for uid_str in unit_ids:
        try:
            uid = uuid.UUID(str(uid_str))
        except (ValueError, TypeError):
            missing_ids.append(str(uid_str))
            continue
        detail = get_property_unit_details(db, uid)
        if not detail:
            missing_ids.append(str(uid))
            continue

        base_price = detail.current_pricing.base_price if detail.current_pricing else Decimal("0")
        total_price = detail.current_pricing.total_estimated_price if detail.current_pricing else Decimal("0")
        currency = detail.current_pricing.currency if detail.current_pricing else "USD"
        sqft = detail.carpet_area_sqft or Decimal("1")
        price_per_sqft = round(base_price / sqft, 2) if sqft > 0 else Decimal("0")

        comparison_items.append({
            "unit_id": str(detail.unit_id),
            "unit_number": detail.unit_number,
            "property_name": detail.property_name,
            "project_name": detail.project_name,
            "company_name": detail.company_name,
            "city": detail.city,
            "address": detail.address_line_1,
            "configuration_type": detail.configuration_type,
            "carpet_area_sqft": float(detail.carpet_area_sqft),
            "floor_number": detail.floor_number,
            "facing": detail.facing,
            "balcony_count": detail.balcony_count,
            "base_price": float(base_price),
            "total_estimated_price": float(total_price),
            "currency": currency,
            "price_per_sqft": float(price_per_sqft),
            "availability_status": detail.current_availability or "unknown",
            "amenities": detail.amenities,
        })

    if len(comparison_items) < 2:
        return AgentToolResponse(
            tool_name="compare_properties",
            success=False,
            error_message=f"Could not find at least 2 valid units to compare in inventory. Missing units: {missing_ids}",
        )

    # Compute comparative metrics
    sorted_by_price = sorted(comparison_items, key=lambda x: x["base_price"])
    sorted_by_size = sorted(comparison_items, key=lambda x: x["carpet_area_sqft"], reverse=True)
    sorted_by_sqft_price = sorted(comparison_items, key=lambda x: x["price_per_sqft"])

    # Common vs unique amenities
    all_amenity_sets = [set(item["amenities"]) for item in comparison_items]
    common_amenities = list(set.intersection(*all_amenity_sets)) if all_amenity_sets else []

    unique_amenities: Dict[str, List[str]] = {}
    for item in comparison_items:
        other_sets = [set(other["amenities"]) for other in comparison_items if other["unit_id"] != item["unit_id"]]
        other_union = set.union(*other_sets) if other_sets else set()
        item_unique = [a for a in item["amenities"] if a not in other_union]
        unique_amenities[item["unit_number"]] = item_unique

    price_diff = sorted_by_price[-1]["base_price"] - sorted_by_price[0]["base_price"]
    currency = comparison_items[0]["currency"]

    summary_text = (
        f"Comparing {len(comparison_items)} properties: "
        f"Unit {sorted_by_price[0]['unit_number']} ({sorted_by_price[0]['property_name']}) is the lowest priced option at "
        f"{currency} {sorted_by_price[0]['base_price']:,.0f} ({currency} {sorted_by_price[0]['price_per_sqft']:.0f}/sqft). "
        f"Unit {sorted_by_size[0]['unit_number']} offers the largest layout at {sorted_by_size[0]['carpet_area_sqft']} sqft. "
        f"Price difference across units is {currency} {price_diff:,.0f}."
    )

    data = {
        "total_compared": len(comparison_items),
        "total_units_compared": len(comparison_items),
        "comparison_items": comparison_items,
        "summary_metrics": {
            "cheapest_unit": sorted_by_price[0]["unit_number"],
            "cheapest_price": sorted_by_price[0]["base_price"],
            "most_expensive_unit": sorted_by_price[-1]["unit_number"],
            "most_expensive_price": sorted_by_price[-1]["base_price"],
            "largest_unit": sorted_by_size[0]["unit_number"],
            "largest_carpet_area_sqft": sorted_by_size[0]["carpet_area_sqft"],
            "best_value_per_sqft": sorted_by_sqft_price[0]["unit_number"],
            "common_amenities": common_amenities,
            "unique_amenities_by_unit": unique_amenities,
            "price_delta": price_diff,
            "currency": currency,
        },
        "comparison_summary": summary_text,
        "missing_unit_ids": missing_ids,
    }

    return AgentToolResponse(
        tool_name="compare_properties",
        success=True,
        data=data,
        anti_hallucination_guidance=(
            "Compare only the exact values provided in 'comparison_items' and 'summary_metrics'. "
            "Never invent missing features, prices, floor plans, or amenities not present in this dataset."
        ),
    )


def tool_get_property_details(db: Session, args: GetPropertyDetailsToolInput) -> AgentToolResponse:
    # 0. Check Demo Mode
    if getattr(settings, "DEMO_DATASET_MODE", False):
        demo_svc = DemoDatasetService.get_instance()
        demo_det = demo_svc.get_property_details(str(args.unit_id))
        if demo_det:
            return AgentToolResponse(
                tool_name="get_property_details",
                success=True,
                data=demo_det,
                anti_hallucination_guidance=(
                    "Describe the demo property specifications, amenities, and estimated price range faithfully. "
                    "If quoting price, state: 'For this demo, the estimated price is around [range]. The actual selling price may vary.'"
                ),
            )

    try:
        parsed_uuid = uuid.UUID(str(args.unit_id))
    except (ValueError, TypeError):
        return AgentToolResponse(
            tool_name="get_property_details",
            success=False,
            error_message=f"Property {args.unit_id} not found in inventory records.",
        )

    details = get_property_unit_details(
        db=db,
        unit_id=parsed_uuid,
        include_pricing_history=args.include_pricing_history
    )
    if not details:
        return AgentToolResponse(
            tool_name="get_property_details",
            success=False,
            error_message=f"Property unit {args.unit_id} not found in inventory records.",
        )
    return AgentToolResponse(
        tool_name="get_property_details",
        success=True,
        data=details.model_dump(),
        anti_hallucination_guidance="Describe only the verified attributes, dimensions, and amenities returned in data."
    )


def tool_get_property_price(db: Session, args: GetPropertyPriceToolInput) -> AgentToolResponse:
    # 0. Check Demo Mode
    if getattr(settings, "DEMO_DATASET_MODE", False):
        demo_svc = DemoDatasetService.get_instance()
        price_info = demo_svc.get_property_price(str(args.unit_id))
        if price_info.get("success"):
            return AgentToolResponse(
                tool_name="get_property_price",
                success=True,
                data=price_info,
                anti_hallucination_guidance=(
                    "State the price strictly using the provided spoken_price_script: "
                    f"\"{price_info['spoken_price_script']}\" "
                    "Never quote demo prices as confirmed seller prices."
                ),
            )

    try:
        parsed_uuid = uuid.UUID(str(args.unit_id))
    except (ValueError, TypeError):
        return AgentToolResponse(
            tool_name="get_property_price",
            success=False,
            error_message="No verified active price found for this unit. State that pricing is currently under review by management. Never estimate or invent a price.",
        )

    active_price = db.execute(
        select(Pricing).where(Pricing.unit_id == parsed_uuid, Pricing.is_active == True)
    ).scalar_one_or_none()

    if not active_price:
        return AgentToolResponse(
            tool_name="get_property_price",
            success=False,
            error_message="No verified active price found for this unit. State that pricing is currently under review by management. Never estimate or invent a price.",
        )

    return AgentToolResponse(
        tool_name="get_property_price",
        success=True,
        data={
            "unit_id": str(args.unit_id),
            "base_price": float(active_price.base_price),
            "currency": active_price.currency,
            "maintenance_charge_monthly": float(active_price.maintenance_charge_monthly),
            "parking_charge": float(active_price.parking_charge),
            "estimated_tax": float(active_price.estimated_tax),
            "total_estimated_price": float(active_price.total_estimated_price),
            "is_verified_active": True,
            "valid_from": active_price.valid_from.isoformat(),
        },
        anti_hallucination_guidance="Quote the exact numbers returned above. Do not promise unverified discounts."
    )


def tool_check_property_availability(db: Session, args: CheckPropertyAvailabilityToolInput) -> AgentToolResponse:
    # 0. Check Demo Mode
    if getattr(settings, "DEMO_DATASET_MODE", False):
        demo_svc = DemoDatasetService.get_instance()
        det = demo_svc.get_property_details(str(args.unit_id))
        if det:
            return AgentToolResponse(
                tool_name="check_property_availability",
                success=True,
                data={
                    "unit_id": str(args.unit_id),
                    "property_name": det["project_name"],
                    "status": "available",
                    "is_demo_mode": True,
                    "message": f"Units at {det['project_name']} are currently open for booking and site visits.",
                },
                anti_hallucination_guidance="Inform the customer of unit availability in demo mode."
            )

    try:
        parsed_uuid = uuid.UUID(str(args.unit_id))
    except (ValueError, TypeError):
        return AgentToolResponse(
            tool_name="check_property_availability",
            success=False,
            error_message=f"Property {args.unit_id} not found in inventory records.",
        )
    report = check_unit_availability(db=db, unit_id=parsed_uuid)
    return AgentToolResponse(
        tool_name="check_property_availability",
        success=True,
        data=report.model_dump(),
        anti_hallucination_guidance="Never assume availability. If status is not 'available', inform the customer honestly that the unit is not open for booking."
    )
    return AgentToolResponse(
        tool_name="check_property_availability",
        success=True,
        data=report.model_dump(),
        anti_hallucination_guidance="Never assume availability. If status is not 'available', inform the customer honestly that the unit is not open for booking."
    )


def tool_extract_requirements(db: Session, args: ExtractRequirementsToolInput) -> AgentToolResponse:
    extracted = extract_requirements_from_text(
        user_utterance=args.customer_utterance,
        existing_requirements=args.existing_requirements
    )
    return AgentToolResponse(
        tool_name="extract_requirements",
        success=True,
        data=extracted.model_dump(),
        anti_hallucination_guidance="If 'missing_fields' is non-empty, use 'clarification_prompt' to ask the customer for the missing criteria before concluding the search."
    )


def tool_create_lead(db: Session, args: CreateLeadToolInput) -> AgentToolResponse:
    lead_input = CreateLeadInput(
        full_name=args.full_name,
        phone=args.phone,
        email=args.email,
        project_id=args.project_id,
        requirements=args.requirements,
        initial_notes=args.notes,
    )
    created_lead = create_customer_lead(db, lead_input)
    return AgentToolResponse(
        tool_name="create_lead",
        success=True,
        data=created_lead.model_dump(),
        anti_hallucination_guidance="Customer profile and qualified lead successfully created in CRM database."
    )


def tool_update_lead(db: Session, args: UpdateLeadToolInput) -> AgentToolResponse:
    try:
        update_input = UpdateLeadInput(
            lead_id=args.lead_id,
            preferred_config=args.preferred_config,
            budget_min=args.budget_min,
            budget_max=args.budget_max,
            preferred_location=args.preferred_location,
            qualification_status=args.qualification_status,
            lead_priority=args.lead_priority,
            append_notes=args.append_notes,
        )
        updated = update_customer_lead(db, update_input)
        return AgentToolResponse(
            tool_name="update_lead",
            success=True,
            data=updated.model_dump(),
        )
    except ValueError as exc:
        return AgentToolResponse(
            tool_name="update_lead",
            success=False,
            error_message=str(exc)
        )


def tool_calculate_lead_priority(db: Session, args: CalculateLeadPriorityToolInput) -> AgentToolResponse:
    evaluation = calculate_lead_priority(
        requirements=args.requirements,
        has_scheduled_visit=args.has_scheduled_visit,
        is_preapproved_loan_or_cash=args.is_preapproved_loan_or_cash,
    )
    return AgentToolResponse(
        tool_name="calculate_lead_priority",
        success=True,
        data=evaluation.model_dump(),
    )


STANDARD_VISIT_SLOTS = [
    "10:00 AM - 11:00 AM",
    "11:30 AM - 12:30 PM",
    "02:00 PM - 03:00 PM",
    "03:30 PM - 04:30 PM",
    "05:00 PM - 06:00 PM",
]


def _parse_visit_date(date_val: Any) -> date:
    """Parses relative ('today', 'tomorrow', 'day after tomorrow', 'Saturday') or formatted date string."""
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    base_date = now_ist.date()
    if not date_val:
        return base_date + timedelta(days=1)

    if isinstance(date_val, date) and not isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, datetime):
        return date_val.date()

    raw = str(date_val).strip().lower()
    if "today" in raw:
        return base_date
    if "day after tomorrow" in raw or "day after" in raw:
        return base_date + timedelta(days=2)
    if "tomorrow" in raw:
        return base_date + timedelta(days=1)

    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for idx, wname in enumerate(weekdays):
        if wname in raw:
            current_wd = base_date.weekday()
            days_ahead = (idx - current_wd) % 7
            if days_ahead == 0:
                days_ahead = 7
            return base_date + timedelta(days=days_ahead)

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass

    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    return base_date + timedelta(days=1)


def _format_time_slot(raw_time: Optional[str]) -> str:
    """Normalizes colloquial spoken time strings ('2pm', '11am', 'morning') to standard slots."""
    if not raw_time:
        return "11:30 AM - 12:30 PM"
    s = str(raw_time).strip().lower()
    if "10" in s or "ten" in s or "morning" in s and "11" not in s:
        return "10:00 AM - 11:00 AM"
    if "11" in s or "eleven" in s or "noon" in s:
        return "11:30 AM - 12:30 PM"
    if "2" in s or "two" in s or "afternoon" in s and "3" not in s and "4" not in s:
        return "02:00 PM - 03:00 PM"
    if "3" in s or "three" in s or "4" in s or "four" in s:
        return "03:30 PM - 04:30 PM"
    if "5" in s or "five" in s or "6" in s or "six" in s or "evening" in s:
        return "05:00 PM - 06:00 PM"
    return str(raw_time).strip()


def tool_check_visit_slots(db: Session, args: CheckVisitSlotsToolInput) -> AgentToolResponse:
    target_date = _parse_visit_date(args.visit_date or args.target_date)
    demo_svc = DemoDatasetService.get_instance()

    # Resolve project name and id
    ident = str(args.project_identifier or getattr(args, "property_name", None) or args.project_id or "").strip()
    proj_details = demo_svc.get_property_details(ident) if ident else None

    # Check if authentic DB projects exist
    db_project = None
    if db is not None and ident:
        try:
            val_uuid = uuid.UUID(ident)
            db_project = db.execute(select(Project).where(Project.id == val_uuid)).scalar_one_or_none()
        except (ValueError, TypeError):
            pass
        if not db_project:
            try:
                db_project = db.execute(select(Project).where(Project.name.ilike(f"%{ident}%"))).scalar_one_or_none()
            except Exception:
                pass

    if not proj_details and not db_project:
        has_projects = False
        if db is not None:
            try:
                has_projects = db.execute(select(Project).limit(1)).scalar_one_or_none() is not None
            except Exception:
                pass
        if has_projects:
            return AgentToolResponse(
                tool_name="check_visit_slots",
                success=False,
                error_message=f"Project with ID or name '{ident}' was not found in active listings.",
            )

    if db_project:
        proj_id = str(db_project.id)
        proj_name = db_project.name
    elif proj_details:
        proj_id = proj_details["project_id"]
        proj_name = proj_details["project_name"]
    else:
        proj_id = ident
        proj_name = ident or "Selected Property"

    # Query existing booked appointments for this project & date
    existing_query = select(Appointment.visit_time).where(
        (Appointment.project_id == proj_id) | (Appointment.property_name.ilike(f"%{proj_name}%")),
        Appointment.visit_date == target_date,
        Appointment.booking_status == "confirmed"
    )
    booked_slots = set(db.scalars(existing_query).all())

    available_slots = [s for s in STANDARD_VISIT_SLOTS if s not in booked_slots]

    date_str = target_date.strftime("%A, %d %B %Y")
    if available_slots:
        voice_text = (
            f"For {proj_name} on {date_str}, we have available visiting slots at "
            f"{', '.join(available_slots[:3])}. Would any of those times work for you?"
        )
    else:
        voice_text = (
            f"All standard visit slots for {proj_name} on {date_str} are fully booked. "
            f"Would you prefer to check the following day?"
        )

    return AgentToolResponse(
        tool_name="check_visit_slots",
        success=True,
        data={
            "project_id": proj_id,
            "property_name": proj_name,
            "target_date": target_date.isoformat(),
            "formatted_date": date_str,
            "available_slots": available_slots,
            "booked_slots": list(booked_slots),
            "total_available_slots": len(available_slots),
            "voice_summary": voice_text,
        },
        anti_hallucination_guidance="Offer only the time slots listed in 'available_slots'. Do not invent other timings.",
    )


def tool_book_site_visit(db: Session, args: BookSiteVisitToolInput) -> AgentToolResponse:
    demo_svc = DemoDatasetService.get_instance()

    # 1. Resolve project
    ident = str(args.property_name or getattr(args, "project_identifier", None) or args.project_id or "").strip()
    proj_details = demo_svc.get_property_details(ident) if ident else None

    if proj_details:
        proj_id = proj_details["project_id"]
        proj_name = proj_details["project_name"]
        city = proj_details.get("city", "Primary Location")
    elif ident:
        proj_id = ident
        proj_name = ident
        city = "Primary Location"
    else:
        proj_id = "PROJ_GENERAL"
        proj_name = "Property Site Visit"
        city = "Primary Location"

    # 2. Resolve date and time slot
    resolved_date = _parse_visit_date(args.visit_date or args.scheduled_start)
    raw_time = args.visit_time
    if not raw_time and args.scheduled_start:
        if isinstance(args.scheduled_start, datetime):
            raw_time = args.scheduled_start.strftime("%I:%M %p")
            if args.scheduled_start.hour < 9 or args.scheduled_start.hour >= 18:
                return AgentToolResponse(
                    tool_name="book_site_visit",
                    success=False,
                    error_message=f"Requested time {args.scheduled_start.strftime('%I:%M %p')} is outside standard project operating hours (09:00 AM to 06:00 PM).",
                    anti_hallucination_guidance="Site visits can only be booked during operating hours between 09:00 AM and 06:00 PM.",
                )
        else:
            raw_time = str(args.scheduled_start)
            try:
                dt_check = datetime.fromisoformat(str(args.scheduled_start))
                if dt_check.hour < 9 or dt_check.hour >= 18:
                    return AgentToolResponse(
                        tool_name="book_site_visit",
                        success=False,
                        error_message=f"Requested time {dt_check.strftime('%I:%M %p')} is outside standard project operating hours (09:00 AM to 06:00 PM).",
                        anti_hallucination_guidance="Site visits can only be booked during operating hours between 09:00 AM and 06:00 PM.",
                    )
            except Exception:
                pass
    formatted_time = _format_time_slot(raw_time)

    # 3. Double-Booking Prevention: Check if already booked for same project, date, and slot
    conflict_query = select(Appointment).where(
        (Appointment.project_id == proj_id) | (Appointment.property_name.ilike(f"%{proj_name}%")),
        Appointment.visit_date == resolved_date,
        Appointment.visit_time == formatted_time,
        Appointment.booking_status == "confirmed"
    )
    conflict = db.scalars(conflict_query).first()
    if conflict:
        # Find next available slot
        existing_booked = set(db.scalars(
            select(Appointment.visit_time).where(
                (Appointment.project_id == proj_id) | (Appointment.property_name.ilike(f"%{proj_name}%")),
                Appointment.visit_date == resolved_date,
                Appointment.booking_status == "confirmed"
            )
        ).all())
        alts = [s for s in STANDARD_VISIT_SLOTS if s not in existing_booked]
        alt_msg = f"Available alternative slots are: {', '.join(alts)}." if alts else "Please choose another date."
        return AgentToolResponse(
            tool_name="book_site_visit",
            success=False,
            error_message=(
                f"The time slot '{formatted_time}' on {resolved_date} for {proj_name} is already reserved. {alt_msg}"
            ),
            anti_hallucination_guidance="Inform the customer of the scheduling conflict and offer one of the alternative available slots.",
        )

    # 4. Create and persist Appointment in development PostgreSQL database
    customer_name = (args.customer_name or "").strip() or "Valued Customer"
    contact_number = (args.contact_number or "").strip() or "Not Provided"

    new_appt = Appointment(
        id=uuid.uuid4(),
        customer_name=customer_name,
        contact_number=contact_number,
        project_id=proj_id,
        property_name=proj_name,
        city=city,
        visit_date=resolved_date,
        visit_time=formatted_time,
        timezone="Asia/Kolkata",
        appointment_type=args.appointment_type or "In-Person Site Visit",
        booking_status="confirmed",
        booking_source="AI Voice",
        customer_notes=args.customer_notes or "Booked via live voice conversation.",
        assigned_agent=args.assigned_agent_name or "Senior Property Advisor",
    )
    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)

    # If customer and project exist as UUIDs, also create SiteVisit record for CRM integration
    if db is not None and args.customer_id:
        try:
            cust_uuid = uuid.UUID(str(args.customer_id))
            proj_uuid = uuid.UUID(str(proj_id))
            sched_start = slot_dt if "slot_dt" in locals() else datetime.combine(resolved_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=11)
            sched_end = sched_start + timedelta(hours=1)
            sv = SiteVisit(
                id=new_appt.id,
                customer_id=cust_uuid,
                project_id=proj_uuid,
                unit_id=uuid.UUID(str(args.unit_id)) if args.unit_id else None,
                scheduled_start=sched_start,
                scheduled_end=sched_end,
                status="scheduled",
                assigned_agent_name=args.assigned_agent_name or "Senior Property Advisor",
                customer_notes=args.customer_notes or "Booked via live voice conversation.",
            )
            db.add(sv)
            db.commit()
        except Exception as sv_exc:
            pass

    date_formatted = resolved_date.strftime("%A, %d %B %Y")
    spoken_confirmation = (
        f"Your visit to {proj_name} in {city} is confirmed for {date_formatted} at {formatted_time}. "
        f"A confirmation has been saved and our senior advisor will be ready to welcome you."
    )

    return AgentToolResponse(
        tool_name="book_site_visit",
        success=True,
        data={
            "visit_id": str(new_appt.id),
            "appointment_id": str(new_appt.id),
            "status": "scheduled",
            "booking_reference": f"BM-{str(new_appt.id)[:8].upper()}",
            "customer_name": customer_name,
            "contact_number": contact_number,
            "project_id": proj_id,
            "property_name": proj_name,
            "city": city,
            "visit_date": resolved_date.isoformat(),
            "formatted_date": date_formatted,
            "visit_time": formatted_time,
            "appointment_type": new_appt.appointment_type,
            "booking_status": new_appt.booking_status,
            "booking_source": new_appt.booking_source,
            "assigned_agent": new_appt.assigned_agent,
            "spoken_confirmation": spoken_confirmation,
        },
        anti_hallucination_guidance="Confirm the appointment with the customer using the exact project name, date, and time.",
    )


def tool_show_property_images(db: Session, args: ShowPropertyImagesToolInput) -> AgentToolResponse:
    demo_svc = DemoDatasetService.get_instance()
    ident = str(args.project_name or args.project_id or "").strip()
    if not ident:
        return AgentToolResponse(
            tool_name="show_property_images",
            success=False,
            error_message="Please specify a project name to display pictures.",
        )

    res = demo_svc.get_property_images(ident)
    if not res.get("success"):
        return AgentToolResponse(
            tool_name="show_property_images",
            success=False,
            error_message=res.get("message") or f"No photos found for {ident}",
        )

    return AgentToolResponse(
        tool_name="show_property_images",
        success=True,
        data=res,
        anti_hallucination_guidance=(
            "State clearly that 4 representative pictures of the property facade, grounds, and living areas "
            "have been displayed on screen. Always remind the customer that these are representative demo pictures."
        ),
    )


def tool_get_dataset_summary(db: Session, args: GetDatasetSummaryToolInput) -> AgentToolResponse:
    demo_svc = DemoDatasetService.get_instance()
    res = demo_svc.get_dataset_summary(city_filter=args.city)
    return AgentToolResponse(
        tool_name="get_dataset_summary",
        success=res.get("success", True),
        data=res,
        anti_hallucination_guidance=(
            "Answer strictly using the counts and voice_summary in the data. "
            "Never invent cities or project numbers outside the active dataset."
        ),
    )


def tool_reschedule_site_visit(db: Session, args: RescheduleSiteVisitToolInput) -> AgentToolResponse:
    try:
        reschedule_input = RescheduleVisitInput(
            visit_id=args.visit_id,
            new_scheduled_start=args.new_scheduled_start,
            new_scheduled_end=args.new_scheduled_end,
            reschedule_reason=args.reschedule_reason,
        )
        updated_visit = reschedule_site_visit(db, reschedule_input)
        return AgentToolResponse(
            tool_name="reschedule_site_visit",
            success=True,
            data=updated_visit.model_dump(),
        )
    except ValueError as exc:
        return AgentToolResponse(
            tool_name="reschedule_site_visit",
            success=False,
            error_message=str(exc)
        )


def tool_cancel_site_visit(db: Session, args: CancelSiteVisitToolInput) -> AgentToolResponse:
    try:
        cancelled_visit = cancel_site_visit(
            db=db,
            visit_id=args.visit_id,
            cancellation_reason=args.cancellation_reason
        )
        return AgentToolResponse(
            tool_name="cancel_site_visit",
            success=True,
            data=cancelled_visit.model_dump(),
        )
    except ValueError as exc:
        return AgentToolResponse(
            tool_name="cancel_site_visit",
            success=False,
            error_message=str(exc)
        )


def tool_transfer_to_human(db: Session, args: TransferToHumanToolInput) -> AgentToolResponse:
    """
    Creates an internal handoff ticket and queues an escalation for human advisor follow-up.
    Note: This logs a handoff request queue ticket; it does NOT execute an automated telephony
    warm transfer / SIP trunk bridge, as external telephony integration is not present.
    """
    handoff_ticket_id = f"HANDOFF-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    # If customer identified, elevate lead priority to urgent
    if args.customer_id:
        latest_lead = db.execute(
            select(Lead).where(Lead.customer_id == args.customer_id).order_by(Lead.created_at.desc())
        ).scalars().first()
        if latest_lead:
            latest_lead.lead_priority = "urgent"
            latest_lead.notes = (latest_lead.notes or "") + f"\n[{now.isoformat()}] Human handoff request queued: {args.reason} ({args.department})"
            db.commit()

    # Record immutable audit event
    db.add(AuditLog(
        user_role="voice_agent",
        action="HUMAN_HANDOFF_REQUEST_QUEUED",
        resource_type="customer",
        resource_id=str(args.customer_id or args.customer_phone or "anonymous"),
        meta_info={
            "ticket_id": handoff_ticket_id,
            "reason": args.reason,
            "department": args.department,
            "summary": args.conversation_summary,
            "telephony_bridged": False,
            "handover_type": "request_queue",
        },
        timestamp=now,
    ))
    db.commit()

    return AgentToolResponse(
        tool_name="transfer_to_human",
        success=True,
        data={
            "handoff_ticket_id": handoff_ticket_id,
            "status": "handoff_request_queued",
            "telephony_bridged": False,
            "department": args.department,
            "customer_message": (
                f"I have logged a priority handoff request with our {args.department} team "
                f"(Ticket #{handoff_ticket_id}). A human property advisor has been notified "
                "and will contact you directly."
            ),
        },
        anti_hallucination_guidance=(
            "Inform the customer that their handoff request has been logged with a ticket number "
            f"({handoff_ticket_id}) and a property specialist will follow up. Never state or promise "
            "that a live telephone transfer is ringing or currently connected."
        )
    )


def tool_query_active_dataset(db: Session, args: QueryActiveDatasetToolInput) -> AgentToolResponse:
    """
    Direct dynamic retrieval tool across the active real estate dataset.
    Answers developer, project, configuration, location, amenities, and FAQ questions.
    """
    # 1. Check if an active dynamic dataset is configured in the database
    active_ds = get_active_dataset(db)
    if active_ds:
        query_str = args.query
        if args.developer and args.developer.lower() not in query_str.lower():
            query_str = f"{args.developer} {query_str}"
        if args.city and args.city.lower() not in query_str.lower():
            query_str = f"{query_str} in {args.city}"
        if args.configuration and args.configuration.lower() not in query_str.lower():
            query_str = f"{query_str} {args.configuration}"

        res = query_dynamic_dataset(db, query_str.strip(), limit=args.limit)
        return AgentToolResponse(
            tool_name="query_active_dataset",
            success=True,
            data=res,
            anti_hallucination_guidance=(
                "Answer the customer's question strictly using the returned verified dataset records. "
                "If a detail (such as price, floor plan, or possession status) is null or unstated in the record, "
                "explicitly inform the customer that it is unstated in the verified portfolio and offer to connect them with a specialist."
            ),
        )

    # 2. Check Demo Mode
    if getattr(settings, "DEMO_DATASET_MODE", False):
        demo_svc = DemoDatasetService.get_instance()
        # A. Check for matching FAQs first
        faq_matches = demo_svc.search_faqs(args.query, limit=args.limit)
        if faq_matches:
            top_faq = faq_matches[0]
            return AgentToolResponse(
                tool_name="query_active_dataset",
                success=True,
                data={
                    "is_demo_mode": True,
                    "faq_found": True,
                    "question": top_faq.get("question"),
                    "answer": top_faq.get("answer"),
                    "category": top_faq.get("category"),
                    "faq_matches": faq_matches,
                },
                anti_hallucination_guidance="Answer the customer's question directly and concisely using the verified FAQ answer.",
            )

        # B. Check demo property search
        demo_matches = demo_svc.search_properties(
            city=args.city,
            developer=args.developer,
            property_type=args.configuration,
            limit=args.limit
        )
        if demo_matches:
            voice_lines = []
            for p in demo_matches[:3]:
                voice_lines.append(
                    f"{p['project_name']} by {p['developer_name']} in {p['locality']}, {p['city']}. {p['spoken_price_script']}"
                )
            return AgentToolResponse(
                tool_name="query_active_dataset",
                success=True,
                data={
                    "is_demo_mode": True,
                    "dataset_grounded": True,
                    "dataset_name": "BrainMagic_RealEstate_v10_Demo",
                    "total_matches": len(demo_matches),
                    "exact_matches": demo_matches,
                    "voice_grounding": " ".join(voice_lines),
                },
                anti_hallucination_guidance=(
                    "For this demo, state estimated prices using the format: "
                    "'For this demo, the estimated price is around [price range]. The actual selling price may vary.' "
                    "Never present demo prices as confirmed seller quotations."
                ),
            )

    query_str = args.query
    if args.developer and args.developer.lower() not in query_str.lower():
        query_str = f"{args.developer} {query_str}"
    if args.city and args.city.lower() not in query_str.lower():
        query_str = f"{query_str} in {args.city}"
    if args.configuration and args.configuration.lower() not in query_str.lower():
        query_str = f"{query_str} {args.configuration}"

    res = query_dynamic_dataset(db, query_str.strip(), limit=args.limit)
    return AgentToolResponse(
        tool_name="query_active_dataset",
        success=True,
        data=res,
        anti_hallucination_guidance=(
            "Answer the customer's question strictly using the returned verified dataset records. "
            "If a detail (such as price, floor plan, or possession status) is null or unstated in the record, "
            "explicitly inform the customer that it is unstated in the verified portfolio and offer to connect them with a specialist."
        ),
    )


def tool_query_business_dataset(db: Session, args: QueryBusinessDatasetToolInput) -> AgentToolResponse:
    """
    Universal tool execution for querying any structured business dataset dynamically.
    Enforces tenant isolation, whitelisted field validation, and anti-hallucination.
    """
    try:
        res = query_universal_dataset(
            db=db,
            query_text=args.query,
            filters=args.filters,
            sort_by=args.sort_by,
            sort_order=args.sort_order or "asc",
            limit=args.limit,
            intent=args.intent or "search",
            aggregate_field=args.aggregate_field,
            aggregate_op=args.aggregate_op,
            record_identifiers=args.record_identifiers,
            conversation_context=args.conversation_context,
            company_id=args.company_id,
            dataset_id=args.dataset_id,
        )
        return AgentToolResponse(
            tool_name="query_business_dataset",
            success=True,
            data=res,
            anti_hallucination_guidance=(
                "Answer the customer's question strictly using the returned verified dataset values. "
                "Never invent specifications, prices, or options not present in the returned attributes. "
                "If an attribute is unlisted or null, clearly state that it is unavailable in the verified dataset."
            ),
        )
    except ValueError as ve:
        return AgentToolResponse(
            tool_name="query_business_dataset",
            success=False,
            error_message=str(ve),
            anti_hallucination_guidance="Inform the user of the invalid field or parameter politely.",
        )
    except Exception as exc:
        return AgentToolResponse(
            tool_name="query_business_dataset",
            success=False,
            error_message=f"Dataset query failure: {str(exc)}",
        )


