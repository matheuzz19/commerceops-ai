import operator
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias, TypedDict

from pydantic import BaseModel, Field

Department: TypeAlias = Literal["sales", "inventory", "finance", "general"]


class NormalizedMessage(BaseModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_type: Literal["text", "audio", "image", "document"] = "text"
    timestamp: datetime


class RouteDecision(BaseModel):
    """Legacy single-route representation retained for external compatibility."""

    department: Department
    confidence: float = Field(ge=0, le=1)
    reason: str


class AgentTask(BaseModel):
    """A single, department-scoped task produced by the structured router."""

    agent: Department = Field(description="The specialist that owns this task.")
    query: str = Field(
        min_length=1, description="Only the portion of the request assigned to this specialist."
    )
    reason: str = Field(min_length=1, description="Why this specialist owns the task.")


class RoutingPlan(BaseModel):
    """Bounded set of tasks that may be dispatched in parallel."""

    tasks: list[AgentTask] = Field(
        min_length=1,
        max_length=4,
        description="Unique specialist tasks. General must never accompany another specialist.",
    )


class SpecialistResult(BaseModel):
    """Structured output returned by one specialist worker."""

    task_index: int = Field(ge=0)
    agent: Department
    query: str
    response: str
    error: str | None = None


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


class PreparedWrite(BaseModel):
    """Resolved write proposal captured before approval and execution."""

    task_index: int = Field(ge=0)
    agent: Literal["sales", "inventory", "finance"]
    query: str
    action: ProposedAction
    resolved_entities: list[ResolvedEntity] = Field(default_factory=list)
    available_quantity: int | None = None
    write_count: int = Field(default=1, ge=1)


class AgentState(TypedDict, total=False):
    """Shared graph state.

    ``total=False`` allows nodes to return typed partial updates. Collection
    fields used by parallel workers define reducers explicitly.
    """

    # Raw trusted graph input. These values are not produced by the model.
    tenant_id: str
    user_id: str
    session_id: str
    message_id: str
    content: str
    content_type: Literal["text", "audio", "image", "document"]
    timestamp: datetime

    # Normalized routing state.
    messages: list[Any]
    normalized_message: NormalizedMessage
    route: RouteDecision | None
    routing_plan: RoutingPlan
    specialist_task: AgentTask
    task_index: int
    specialist_results: Annotated[list[SpecialistResult], operator.add]

    # State reserved by the source-of-truth specification for later milestones.
    intent: str | None
    resolved_entities: Annotated[list[ResolvedEntity], operator.add]
    proposed_actions: Annotated[list[ProposedAction], operator.add]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    requires_confirmation: bool
    prepared_writes: Annotated[list[PreparedWrite], operator.add]
    writes_approved: bool
    write_policy_error: str | None
    confirmation_request: dict[str, Any] | None
    error: str | None
    final_response: str | None
