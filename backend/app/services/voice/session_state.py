import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.services.real_estate.requirements import ExtractedCustomerRequirements
from app.services.real_estate.matcher import CustomerPreferences


class SessionState(BaseModel):
    """
    Maintains stateful customer requirements and interaction context
    across multiple conversation turns within an active voice session.
    
    Guarantees:
    - Retains previous preferences when customer updates specific attributes (e.g. changing budget retains 2BHK and OMR).
    - Tracks viewed, compared, and booked property IDs.
    - Prevents cross-customer session hijacking through ownership checks.
    - Provides safe, controlled session cleanup.
    """
    session_id: str
    customer_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    user_role: str = "customer"
    language: str = "en-US"
    voice_id: str = "kiara"
    requirements: ExtractedCustomerRequirements = Field(default_factory=ExtractedCustomerRequirements)
    saved_requirements_from_profile: Optional[Dict[str, Any]] = None
    viewed_properties: List[uuid.UUID] = Field(default_factory=list)
    compared_properties: List[uuid.UUID] = Field(default_factory=list)
    last_search_criteria: Optional[Dict[str, Any]] = None
    selected_property: Optional[Dict[str, Any]] = None  # Active property context for follow-up questions
    booked_visit_id: Optional[uuid.UUID] = None
    clarification_questions_count: int = 0
    turn_count: int = 0
    history: List[Dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def set_selected_property(self, property_data: Dict[str, Any]) -> None:
        """Sets the active focused property for seamless follow-up questions."""
        self.selected_property = property_data
        self.last_updated_at = datetime.now(timezone.utc)

    def get_selected_property(self) -> Optional[Dict[str, Any]]:
        """Retrieves the active focused property context."""
        return self.selected_property

    def set_language(self, language: str, voice_id: Optional[str] = None) -> None:
        """
        Switches the session conversational language (e.g. 'hi-IN' or 'en-US')
        and optional voiceId while strictly preserving accumulated customer
        requirements, viewed properties, and search context.
        """
        self.language = language
        if voice_id:
            self.voice_id = voice_id
        elif language.lower().startswith("hi"):
            self.voice_id = "kiara"
        else:
            self.voice_id = "matthew"
        self.last_updated_at = datetime.now(timezone.utc)

    def update_requirements(self, new_req: ExtractedCustomerRequirements) -> Dict[str, Any]:
        """
        Intelligently merges new requirements into the accumulated session requirements.
        Preserves previously established fields if the new utterance does not modify them.
        Returns a changelog dictionary of modified fields.
        """
        changes: Dict[str, Any] = {}
        old_req = self.requirements.model_copy(deep=True)

        if new_req.intent_type and new_req.intent_type != self.requirements.intent_type:
            changes["intent_type"] = (self.requirements.intent_type, new_req.intent_type)
            self.requirements.intent_type = new_req.intent_type

        if new_req.preferred_city:
            if new_req.preferred_city != self.requirements.preferred_city:
                changes["preferred_city"] = (self.requirements.preferred_city, new_req.preferred_city)
                self.requirements.preferred_city = new_req.preferred_city
                # If city changed, reset neighborhood if it doesn't match
                if self.requirements.preferred_location and self.requirements.preferred_location != new_req.preferred_location:
                    self.requirements.preferred_location = new_req.preferred_location

        if new_req.preferred_location and new_req.preferred_location != self.requirements.preferred_location:
            changes["preferred_location"] = (self.requirements.preferred_location, new_req.preferred_location)
            self.requirements.preferred_location = new_req.preferred_location

        if new_req.configuration_type and new_req.configuration_type != self.requirements.configuration_type:
            changes["configuration_type"] = (self.requirements.configuration_type, new_req.configuration_type)
            self.requirements.configuration_type = new_req.configuration_type

        if new_req.property_type and new_req.property_type != self.requirements.property_type:
            changes["property_type"] = (self.requirements.property_type, new_req.property_type)
            self.requirements.property_type = new_req.property_type

        if new_req.budget_max is not None and new_req.budget_max != self.requirements.budget_max:
            changes["budget_max"] = (self.requirements.budget_max, new_req.budget_max)
            self.requirements.budget_max = new_req.budget_max

        if new_req.budget_min is not None and new_req.budget_min != self.requirements.budget_min:
            changes["budget_min"] = (self.requirements.budget_min, new_req.budget_min)
            self.requirements.budget_min = new_req.budget_min

        if new_req.currency and new_req.currency != self.requirements.currency:
            changes["currency"] = (self.requirements.currency, new_req.currency)
            self.requirements.currency = new_req.currency

        if new_req.desired_amenities:
            for amen in new_req.desired_amenities:
                if amen not in self.requirements.desired_amenities:
                    self.requirements.desired_amenities.append(amen)
                    changes.setdefault("amenities_added", []).append(amen)

        if new_req.purchase_timeline and new_req.purchase_timeline != self.requirements.purchase_timeline:
            changes["purchase_timeline"] = (self.requirements.purchase_timeline, new_req.purchase_timeline)
            self.requirements.purchase_timeline = new_req.purchase_timeline

        # Re-evaluate completeness
        missing = []
        if not self.requirements.preferred_city and not self.requirements.preferred_location:
            missing.append("location")
        if not self.requirements.configuration_type:
            missing.append("configuration (e.g. 2BHK, 3BHK)")
        if not self.requirements.budget_max:
            missing.append("budget")

        self.requirements.missing_fields = missing
        self.requirements.is_complete = len(missing) == 0
        if missing:
            self.requirements.clarification_prompt = (
                f"To help find the best options, could you please specify your preferred {', '.join(missing)}?"
            )
        else:
            self.requirements.clarification_prompt = None

        self.last_updated_at = datetime.now(timezone.utc)
        self.turn_count += 1
        self.history.append({
            "turn": self.turn_count,
            "timestamp": self.last_updated_at.isoformat(),
            "changes": changes,
            "active_requirements": self.requirements.model_dump(),
        })

        return changes

    def remove_requirement(self, field_name: str) -> bool:
        """
        Selectively removes or relaxes a customer requirement.
        Accepts: 'budget', 'location', 'city', 'configuration', 'amenities', or specific amenity name.
        """
        fn = field_name.strip().lower()
        removed = False

        if fn in ["budget", "price", "budget_max", "max_budget"]:
            self.requirements.budget_max = None
            self.requirements.budget_min = None
            removed = True
        elif fn in ["location", "city", "preferred_city"]:
            self.requirements.preferred_city = None
            self.requirements.preferred_location = None
            removed = True
        elif fn in ["config", "configuration", "bhk", "layout"]:
            self.requirements.configuration_type = None
            removed = True
        elif fn in ["amenities", "amenity"]:
            self.requirements.desired_amenities = []
            removed = True
        else:
            # Check if matching a specific amenity in list
            original_len = len(self.requirements.desired_amenities)
            self.requirements.desired_amenities = [
                a for a in self.requirements.desired_amenities if a.lower() != fn
            ]
            if len(self.requirements.desired_amenities) < original_len:
                removed = True

        if removed:
            self.last_updated_at = datetime.now(timezone.utc)
            # Recompute completeness
            missing = []
            if not self.requirements.preferred_city and not self.requirements.preferred_location:
                missing.append("location")
            if not self.requirements.configuration_type:
                missing.append("configuration (e.g. 2BHK, 3BHK)")
            if not self.requirements.budget_max:
                missing.append("budget")

            self.requirements.missing_fields = missing
            self.requirements.is_complete = len(missing) == 0
            if missing:
                self.requirements.clarification_prompt = (
                    f"To help find the best options, could you please specify your preferred {', '.join(missing)}?"
                )
            else:
                self.requirements.clarification_prompt = None

        return removed

    def get_active_preferences(self) -> CustomerPreferences:
        """Converts accumulated session requirements into a CustomerPreferences object for matching."""
        return CustomerPreferences(
            preferred_city=self.requirements.preferred_city,
            preferred_location=self.requirements.preferred_location,
            preferred_config=self.requirements.configuration_type,
            budget_min=self.requirements.budget_min,
            budget_max=self.requirements.budget_max,
            preferred_currency=self.requirements.currency,
            desired_amenities=self.requirements.desired_amenities,
        )

    def check_ownership(self, requesting_customer_id: Optional[uuid.UUID], requesting_role: str) -> bool:
        """
        Enforces strict customer session ownership:
        - Super Owner and Admin roles may inspect according to their RBAC permissions.
        - Customer role may ONLY access their own session.
        """
        if requesting_role in ["super_owner", "admin"]:
            return True
        if self.customer_id is None:
            return True
        return self.customer_id == requesting_customer_id

    def reset(self) -> None:
        """Safely cleans up memory and marks session inactive."""
        self.is_active = False
        self.viewed_properties.clear()
        self.compared_properties.clear()
        self.selected_property = None
        self.history.clear()
