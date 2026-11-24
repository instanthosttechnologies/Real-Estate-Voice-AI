import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.lead import Lead
from app.models.customer import Customer
from app.models.pricing import Pricing
from app.models.audit_log import AuditLog
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

    # 2. Check if DEMO_DATASET_MODE is active
    if getattr(settings, "DEMO_DATASET_MODE", False):
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


def tool_check_visit_slots(db: Session, args: CheckVisitSlotsToolInput) -> AgentToolResponse:
    try:
        slots_resp = get_available_visit_slots(
            db=db,
            project_id=args.project_id,
            target_date=args.target_date
        )
        available_only = [s.model_dump() for s in slots_resp.slots if s.is_available]
        return AgentToolResponse(
            tool_name="check_visit_slots",
            success=True,
            data={
                "project_id": str(args.project_id),
                "target_date": args.target_date.isoformat(),
                "available_slots": available_only,
                "total_available_slots": len(available_only),
            },
            anti_hallucination_guidance="Offer only the time slots listed in 'available_slots'. Do not offer time slots outside operating hours (9 AM - 6 PM)."
        )
    except ValueError as exc:
        return AgentToolResponse(
            tool_name="check_visit_slots",
            success=False,
            error_message=str(exc)
        )


def tool_book_site_visit(db: Session, args: BookSiteVisitToolInput) -> AgentToolResponse:
    try:
        book_input = BookVisitInput(
            customer_id=args.customer_id,
            project_id=args.project_id,
            unit_id=args.unit_id,
            scheduled_start=args.scheduled_start,
            scheduled_end=args.scheduled_end,
            assigned_agent_name=args.assigned_agent_name,
            customer_notes=args.customer_notes,
        )
        visit_resp = book_site_visit(db, book_input)
        from app.core.config import settings
        guidance = (
            "Dry-run test mode is active: clearly inform the customer that this appointment is provisionally scheduled for testing purposes and is not permanently confirmed in production."
            if getattr(settings, "DRY_RUN_TEST_MODE", False)
            else "Confirm the appointment with the customer using the exact date, time, and project name in the response."
        )
        return AgentToolResponse(
            tool_name="book_site_visit",
            success=True,
            data=visit_resp.model_dump(),
            anti_hallucination_guidance=guidance
        )
    except ValueError as exc:
        return AgentToolResponse(
            tool_name="book_site_visit",
            success=False,
            error_message=str(exc)
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


