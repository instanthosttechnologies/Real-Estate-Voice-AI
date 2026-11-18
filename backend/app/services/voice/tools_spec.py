from typing import Any, Dict, List
from app.services.agent.dispatcher import AGENT_TOOL_REGISTRY


TOOL_DESCRIPTIONS: Dict[str, str] = {
    "search_properties": (
        "Search genuine database properties by city, location keyword, developer, project, property type, "
        "BHK configuration, budget, ISO currency (e.g. USD, INR), carpet area, and amenities. "
        "Always returns verified database records. Never fabricates properties."
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


def get_agent_tools_spec() -> List[Dict[str, Any]]:
    """
    Generates Amazon Nova 2.5 Sonic / Bedrock compatible JSON tool specifications
    from the 13 validated Pydantic schemas in AGENT_TOOL_REGISTRY.
    """
    tools_spec: List[Dict[str, Any]] = []

    for tool_name, (schema_cls, _) in AGENT_TOOL_REGISTRY.items():
        # Generate Pydantic JSON Schema
        schema = schema_cls.model_json_schema()

        # Clean schema definitions for LLM tool consumption
        clean_properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        description = TOOL_DESCRIPTIONS.get(tool_name, schema.get("description", f"Execute {tool_name}"))

        tool_def = {
            "toolSpec": {
                "name": tool_name,
                "description": description,
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": clean_properties,
                        "required": required_fields,
                    }
                },
            }
        }
        tools_spec.append(tool_def)

    return tools_spec
