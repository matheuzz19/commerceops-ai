from datetime import datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class NormalizedMessage(BaseModel):
    tenant_id: str
    user_id: str
    session_id: str
    message_id: str
    content: str
    content_type: Literal["text", "audio", "image", "document"] = "text"
    timestamp: datetime


class RouteDecision(BaseModel):
    department: Literal["sales", "inventory", "finance", "general"]
    confidence: float = Field(ge=0, le=1)
    reason: str


class ResolvedEntity(BaseModel):
    entity_type: Literal["customer", "product", "order", "transaction"]
    id: str
    display_name: str
    source_tool_call_id: str


class ProposedAction(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    risk_level: Literal["low", "medium", "high"]
    requires_confirmation: bool


class AgentState(TypedDict):
    messages: list[Any]
    normalized_message: NormalizedMessage
    route: RouteDecision | None
    tenant_id: str
    user_id: str
    session_id: str
    intent: str | None
    resolved_entities: list[ResolvedEntity]
    proposed_actions: list[ProposedAction]
    tool_results: list[dict[str, Any]]
    requires_confirmation: bool
    confirmation_request: dict[str, Any] | None
    error: str | None
    final_response: str | None
