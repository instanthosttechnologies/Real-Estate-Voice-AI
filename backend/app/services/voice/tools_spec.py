import json
from typing import Any, Dict, List, Optional
from app.services.agent.dispatcher import AGENT_TOOL_REGISTRY


TOOL_DESCRIPTIONS: Dict[str, str] = {
    "query_active_dataset": (
        "Query the active verified real estate portfolio dataset for developers (DLF, Godrej, Lodha, Oberoi, Prestige, Sobha, etc.), "
        "projects, cities (Gurugram, Mumbai, Bengaluru, Pune, etc.), configurations (2BHK, 3BHK, Penthouses, Offices, Plots), "
        "and amenities. Returns concise, verified facts directly from the active dataset."
    ),
    "query_business_dataset": (
        "Universal query tool for structured business datasets. Supports natural-language questions, "
        "exact or partial filters, numeric comparisons (e.g. price, year, quantity, ratings), "
        "sorting, counting, aggregation (min, max, avg, sum), and side-by-side record comparison. "
        "Operates strictly on verified Admin-approved columns."
    ),
    "search_properties": (
        "Search genuine database properties by city, location keyword, developer, project, property type, "
        "BHK configuration, budget, ISO currency (e.g. USD, INR), carpet area, and amenities. "
        "Always returns verified database records. Never fabricates properties."
    ),
    "show_property_images": (
        "Display 4 representative demo pictures (building facade, entrance/grounds, living area, master bedroom) "
        "of a specific property or project on the customer's screen. Enforces demo disclaimer."
    ),
    "get_dataset_summary": (
        "Retrieve dynamic, verified real estate portfolio counts and statistics. "
        "Returns total actual projects (123), total unique cities (19), representative image count (492), "
        "or specific project counts and top developers for a requested city (e.g. Gurugram, Bengaluru, Mumbai, Pune)."
    ),
    "get_property_details": (
        "Retrieve verified specifications and current pricing for a specific property unit by its unit UUID. "
        "Optionally retrieves historical pricing records."
    ),
    "get_property_price": (
        "Retrieve the active verified price and breakdown (base price, maintenance, taxes) for a property unit. "
        "Guarantees that expired or inactive prices are never quoted."
    ),
    "check_property_availability": (
        "Check the real-time availability status ('available', 'reserved', 'sold', 'blocked') of a property unit."
    ),
    "compare_properties": (
        "Compare 2 to 5 property units side-by-side using authentic database records. "
        "Provides comparison of price, price per sqft, configuration, area, floor, facing, availability, and amenities."
    ),
    "extract_requirements": (
        "Extract structured real estate preferences (city, BHK layout, budget range, ISO currency, amenities) "
        "from customer conversational speech."
    ),
    "create_lead": (
        "Create a customer lead record storing contact details, budget, layout requirements, and initial priority."
    ),
    "update_lead": (
        "Update an existing customer lead's status, notes, or requirements."
    ),
    "calculate_lead_priority": (
        "Calculate deterministic lead qualification priority ('high', 'medium', 'low') and score (0-100) "
        "based on verified customer intent, loan pre-approval, and scheduled site visits."
    ),
    "check_visit_slots": (
        "Check available 1-hour appointment slots for a project on a specific date, evaluated in the project's "
        "local timezone between operating hours (09:00 - 18:00 local time)."
    ),
    "book_site_visit": (
        "Book a site visit appointment for a customer at a project. Enforces double-booking prevention, "
        "capacity checks, and concurrency locks."
    ),
    "reschedule_site_visit": (
        "Reschedule an existing site visit appointment to a new available time slot within operating hours."
    ),
    "cancel_site_visit": (
        "Cancel an existing site visit appointment and record the cancellation reason."
    ),
    "transfer_to_human": (
        "Queue an internal escalation ticket for a human property specialist callback. "
        "Does not bridge a live phone call; queues an urgent callback ticket."
    ),
    "request_human_handoff": (
        "Alias for transfer_to_human. Queues an urgent escalation ticket for human specialist follow-up."
    ),
}


def _sanitize_property(prop: Dict[str, Any], defs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively cleans and normalizes a property schema to comply with Amazon Bedrock
    Nova Sonic strict JSON schema requirements:
    - Inlines all $ref references from definitions.
    - Flattens anyOf/oneOf union types with null into clean primitive types.
    - Strips title, $defs, $ref, and complex combinators that trigger validationException.
    - Preserves parameter descriptions and nested object properties.
    """
    # 1. Resolve $ref
    if "$ref" in prop:
        ref_path = prop["$ref"]
        ref_name = ref_path.split("/")[-1]
        if ref_name in defs:
            resolved = defs[ref_name].copy()
            return _sanitize_schema(resolved, defs)
        return {"type": "object", "properties": {}}

    # 2. Flatten anyOf (e.g. Union[str, None] or Union[Decimal, str, None])
    if "anyOf" in prop:
        non_null_variants = [v for v in prop["anyOf"] if v.get("type") != "null"]
        if non_null_variants:
            primary = non_null_variants[0]
            cleaned = _sanitize_property(primary, defs)
            if "description" in prop and "description" not in cleaned:
                cleaned["description"] = prop["description"]
            if "default" in prop and prop["default"] is not None:
                cleaned["default"] = prop["default"]
            return cleaned
        return {"type": "string"}

    cleaned: Dict[str, Any] = {}
    prop_type = prop.get("type")
    if prop_type:
        cleaned["type"] = prop_type
    elif "properties" in prop:
        cleaned["type"] = "object"

    if "description" in prop:
        cleaned["description"] = prop["description"]

    if prop.get("type") == "array" and "items" in prop:
        cleaned["items"] = _sanitize_property(prop["items"], defs)

    if prop.get("type") == "object" or "properties" in prop:
        cleaned["type"] = "object"
        cleaned["properties"] = {
            k: _sanitize_property(v, defs) for k, v in prop.get("properties", {}).items()
        }
        if "required" in prop:
            cleaned["required"] = prop["required"]

    if "enum" in prop:
        cleaned["enum"] = prop["enum"]

    return cleaned


def _sanitize_schema(schema: Dict[str, Any], defs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produces a top-level JSON Schema strictly conforming to Bedrock Nova requirements:
    root type MUST be 'object', with only 'type', 'properties', and 'required' permitted.
    """
    properties: Dict[str, Any] = {}
    for prop_name, prop_val in schema.get("properties", {}).items():
        properties[prop_name] = _sanitize_property(prop_val, defs)

    required: List[str] = schema.get("required", [])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def get_agent_tools_spec(active_dataset: Optional[Any] = None) -> List[Dict[str, Any]]:
    """
    Generates Amazon Nova 2.5 Sonic / Bedrock compatible JSON tool specifications
    from the validated Pydantic schemas in AGENT_TOOL_REGISTRY.
    Guarantees:
    - Zero $defs or $ref references (all nested models inlined).
    - Zero anyOf/oneOf union types (flattened to compliant primitive/object types).
    - Strict object root schema conforming to Amazon Bedrock Nova specifications.
    - Dynamically informs Nova Sonic of the approved dataset fields when active_dataset is provided.
    """
    tools_spec: List[Dict[str, Any]] = []

    for tool_name, (schema_cls, _) in AGENT_TOOL_REGISTRY.items():
        raw_schema = schema_cls.model_json_schema()
        defs = raw_schema.get("$defs", {})
        cleaned_json_schema = _sanitize_schema(raw_schema, defs)

        description = TOOL_DESCRIPTIONS.get(
            tool_name,
            raw_schema.get("description", f"Execute {tool_name}")
        )

        if tool_name == "query_business_dataset" and active_dataset:
            approved_cols = getattr(active_dataset, "approved_fields", None)
            domain = getattr(active_dataset, "domain_name", None) or "Business"
            if approved_cols:
                description += (
                    f" Active dataset: '{active_dataset.name}'. Domain: '{domain}'. "
                    f"Allowed queryable fields: {', '.join(approved_cols)}."
                )

        tool_def = {
            "toolSpec": {
                "name": tool_name,
                "description": description,
                "inputSchema": {
                    "json": cleaned_json_schema
                },
            }
        }
        tools_spec.append(tool_def)

    return tools_spec
