"""Versioned synthetic evaluation contracts; replay inputs are separate from references."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from commerceops.graph.state import Department


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[Department] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    confirmation: bool = False
    clarification: bool = False
    error: str | None = None
    contains: str | None = None
    effects: dict[str, Any] = Field(default_factory=dict)
    allowed: bool | None = None


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    kind: Literal["workflow", "policy", "probe"] = "workflow"
    replay_agents: list[Department] = Field(min_length=1)
    plans: dict[str, dict[str, Any]] = Field(default_factory=dict)
    approval: bool | None = None
    fault: Literal["failure", "invalid_output"] | None = None
    fault_tool: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    write_count: int = Field(default=1, ge=1)
    resolve: list[str] = Field(default_factory=list)
    reference: Reference


class CaseResult(BaseModel):
    id: str
    dataset: str
    routing_correct: bool
    tools_correct: bool
    entities_correct: bool
    task_completed: bool
    forbidden_tool_call: bool = False
    tenant_leakage: bool = False
    hitl_correct: bool = True
    invalid_success_claim: bool = False
    latency_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error_code: str | None = None
    trace_id: str | None = None
    resume_trace_id: str | None = None
