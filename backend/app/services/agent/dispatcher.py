import logging
from typing import Any, Callable, Dict, Tuple, Type
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

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
    TransferToHumanToolInput,
    UpdateLeadToolInput,
    CalculateLeadPriorityToolInput,
)
from app.services.agent import tools

logger = logging.getLogger("agent_dispatcher")

# Registry: tool_name -> (Schema, Function)
AGENT_TOOL_REGISTRY: Dict[str, Tuple[Type[BaseModel], Callable[[Session, Any], AgentToolResponse]]] = {
    "search_properties": (SearchPropertiesToolInput, tools.tool_search_properties),
    "get_property_details": (GetPropertyDetailsToolInput, tools.tool_get_property_details),
    "get_property_price": (GetPropertyPriceToolInput, tools.tool_get_property_price),
    "check_property_availability": (CheckPropertyAvailabilityToolInput, tools.tool_check_property_availability),
    "compare_properties": (ComparePropertiesToolInput, tools.tool_compare_properties),
    "extract_requirements": (ExtractRequirementsToolInput, tools.tool_extract_requirements),
    "create_lead": (CreateLeadToolInput, tools.tool_create_lead),
    "update_lead": (UpdateLeadToolInput, tools.tool_update_lead),
    "calculate_lead_priority": (CalculateLeadPriorityToolInput, tools.tool_calculate_lead_priority),
    "check_visit_slots": (CheckVisitSlotsToolInput, tools.tool_check_visit_slots),
    "book_site_visit": (BookSiteVisitToolInput, tools.tool_book_site_visit),
    "reschedule_site_visit": (RescheduleSiteVisitToolInput, tools.tool_reschedule_site_visit),
    "cancel_site_visit": (CancelSiteVisitToolInput, tools.tool_cancel_site_visit),
    "transfer_to_human": (TransferToHumanToolInput, tools.tool_transfer_to_human),
    "request_human_handoff": (TransferToHumanToolInput, tools.tool_transfer_to_human),
}


def dispatch_agent_tool(
    db: Session,
    tool_name: str,
    raw_arguments: Dict[str, Any]
) -> AgentToolResponse:
    """
    Validates tool invocation against strict Pydantic schemas and executes against live database.
    Provides structured error reporting to prevent LLM hallucinations upon malformed calls.
    """
    clean_name = tool_name.strip()
    if clean_name not in AGENT_TOOL_REGISTRY:
        logger.warning(f"Attempted execution of unregistered tool: {clean_name}")
        return AgentToolResponse(
            tool_name=clean_name,
            success=False,
            error_message=f"Tool '{clean_name}' is not recognized. Available tools: {list(AGENT_TOOL_REGISTRY.keys())}",
        )

    schema_cls, tool_fn = AGENT_TOOL_REGISTRY[clean_name]

    # 1. Strict schema validation
    try:
        validated_args = schema_cls(**raw_arguments)
    except ValidationError as err:
        logger.warning(f"Tool {clean_name} validation error: {err}")
        return AgentToolResponse(
            tool_name=clean_name,
            success=False,
            error_message=f"Invalid arguments for {clean_name}: {err.errors()}",
        )
    except Exception as exc:
        return AgentToolResponse(
            tool_name=clean_name,
            success=False,
            error_message=f"Argument parsing error: {exc}",
        )

    # 2. Deterministic execution
    try:
        return tool_fn(db, validated_args)
    except Exception as exc:
        logger.error(f"Execution failure in tool {clean_name}: {exc}", exc_info=True)
        return AgentToolResponse(
            tool_name=clean_name,
            success=False,
            error_message=f"Internal database execution failure in {clean_name}: {str(exc)}",
        )
