"""Checkpoint preparation before review; execute only captured write arguments."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from pydantic import BaseModel

from commerceops.agents.runtime import ToolClientFactory, create_tool_client, verified_call
from commerceops.graph.policy import PolicyContext, approval_grants, evaluate_policy
from commerceops.graph.state import (
    AgentState,
    Department,
    PreparedWrite,
    ProposedAction,
    ResolvedEntity,
    SpecialistResult,
)
from commerceops.mcp.context import Specialist
from commerceops.mcp.tools.schemas import (
    CustomerResultData,
    InventoryMovementResultData,
    OrderResultData,
    TransactionResultData,
)


def prepare_write(
    state: AgentState,
    action: ProposedAction,
    *,
    records: list[dict[str, object]] | None = None,
    entities: list[ResolvedEntity] | None = None,
    available_quantity: int | None = None,
    write_count: int = 1,
) -> dict[str, object]:
    task = state["specialist_task"]
    if task.agent == "general":
        raise ValueError("General cannot prepare writes.")
    prepared = PreparedWrite(
        task_index=state["task_index"],
        agent=task.agent,
        query=task.query,
        action=action.model_copy(deep=True),
        resolved_entities=entities or [],
        available_quantity=available_quantity,
        write_count=write_count,
    )
    return {
        "prepared_writes": [prepared],
        "proposed_actions": [prepared.action],
        "resolved_entities": prepared.resolved_entities,
        "tool_results": records or [],
    }


def evaluate_writes(state: AgentState) -> dict[str, object]:
    """Save the policy decision and review payload before the interrupt node."""
    writes = sorted(state.get("prepared_writes", []), key=lambda item: item.task_index)
    if not writes:
        return {"writes_approved": False, "write_policy_error": None,
                "requires_confirmation": False, "confirmation_request": None}
    write_count = sum(item.write_count for item in writes)
    decisions = [
        evaluate_policy(
            item.action,
            PolicyContext(
                state["tenant_id"], Specialist(item.agent),
                item.resolved_entities, item.available_quantity,
            ),
            proposed_write_count=write_count,
        )
        for item in writes
    ]
    if any(not decision.allowed for decision in decisions):
        return {"writes_approved": False, "write_policy_error": "POLICY_DENIED",
                "requires_confirmation": False, "confirmation_request": None}
    if any(result.error for result in state.get("specialist_results", [])):
        return {"writes_approved": False, "write_policy_error": "PREPARATION_FAILED",
                "requires_confirmation": False, "confirmation_request": None}
    if not any(decision.requires_confirmation for decision in decisions):
        return {"writes_approved": True, "write_policy_error": None,
                "requires_confirmation": False, "confirmation_request": None}

    actions = [item.action.model_dump(mode="json") for item in writes]
    reasons = list(dict.fromkeys(
        decision.reason for decision in decisions if decision.requires_confirmation
    ))
    payload: dict[str, object] = {
        "message": "Please approve this action." if len(writes) == 1 else (
            "Please approve all proposed actions. No writes have been executed."
        ),
        "actions": actions,
        "risk_reason": " ".join(reasons),
    }
    if len(writes) == 1:
        payload["action"] = actions[0]
    return {
        "writes_approved": False, "write_policy_error": None,
        "requires_confirmation": True, "confirmation_request": payload,
    }


def review_writes(state: AgentState) -> dict[str, object]:
    """Resume only the saved decision; do not replan, resolve, or reevaluate it."""
    if not state.get("requires_confirmation"):
        return {}
    payload = state["confirmation_request"]
    if payload is None:
        raise ValueError("A required confirmation must include its saved payload.")
    response = interrupt(payload)
    approved = response is True or (
        isinstance(response, Mapping) and response.get("approved") is True
    )
    return {
        "writes_approved": approved,
        "write_policy_error": None if approved else "ACTION_REJECTED",
        "requires_confirmation": False,
        "confirmation_request": None,
    }


def make_execute_writes(
    client_factory: ToolClientFactory,
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    async def execute_writes(state: AgentState) -> dict[str, object]:
        results: list[SpecialistResult] = []
        records: list[dict[str, Any]] = []
        for item in state.get("prepared_writes", []):
            error = state.get("write_policy_error")
            if not state.get("writes_approved"):
                error = error or "POLICY_DENIED"
                response = (
                    "The action was rejected and was not executed."
                    if error == "ACTION_REJECTED" else
                    "The action was not executed because request validation failed."
                )
            else:
                context = PolicyContext(
                    state["tenant_id"], Specialist(item.agent),
                    item.resolved_entities, item.available_quantity,
                )
                # Revalidate the saved proposal; never ask the planner to replace it.
                decision = evaluate_policy(item.action, context)
                if not decision.allowed:
                    error = "POLICY_DENIED"
                    response = decision.reason
                else:
                    client = create_tool_client(
                        client_factory, UUID(state["tenant_id"]), Specialist(item.agent),
                        approval_grants(item.action, available_quantity=item.available_quantity),
                    )
                    schemas: dict[str, type[BaseModel]] = {
                        "create_customer": CustomerResultData,
                        "create_order": OrderResultData,
                        "update_order": OrderResultData,
                        "create_inventory_movement": InventoryMovementResultData,
                        "create_transaction": TransactionResultData,
                    }
                    schema = schemas[item.action.tool_name]
                    data, result, record = await verified_call(
                        client, item.action.tool_name, item.action.arguments, schema
                    )
                    records.append(record)
                    if data is None:
                        error = "TOOL_FAILED"
                        response = result.error.message if result.error else "The operation failed."
                    elif isinstance(data, CustomerResultData):
                        response = f"Customer {data.customer.name} was created successfully."
                    elif isinstance(data, OrderResultData):
                        verb = "created" if item.action.tool_name == "create_order" else "updated"
                        response = f"Order {data.order.id} was {verb} successfully."
                        if item.action.tool_name == "create_order":
                            response += f" Total: {data.order.total_amount}."
                    elif isinstance(data, InventoryMovementResultData):
                        response = (
                            f"Inventory movement {data.movement.id} was created successfully."
                        )
                    else:
                        assert isinstance(data, TransactionResultData)
                        response = (
                            f"Expense transaction {data.transaction.id} was recorded successfully."
                        )
            results.append(SpecialistResult(
                task_index=item.task_index, agent=item.agent, query=item.query,
                response=response, error=error,
            ))
        return {"specialist_results": results, "tool_results": records}

    return execute_writes


def dispatch_writes(state: AgentState) -> list[Send] | str:
    writes = state.get("prepared_writes", [])
    if not writes:
        return "aggregate_results"
    return [Send("execute_write", {
        "tenant_id": state["tenant_id"],
        "prepared_writes": [item],
        "writes_approved": state.get("writes_approved", False),
        "write_policy_error": state.get("write_policy_error"),
    }) for item in writes]


def standalone_specialist(
    prepare: Callable[[AgentState], Awaitable[dict[str, object]]],
    client_factory: ToolClientFactory,
    agent: Department,
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    """Keep direct specialist entrypoints on the same checkpoint-safe pipeline."""
    builder = StateGraph(AgentState)
    builder.add_node("prepare", cast(Any, prepare))
    builder.add_node("evaluate", evaluate_writes)
    builder.add_node("review", review_writes)
    builder.add_node("execute", cast(Any, make_execute_writes(client_factory)))
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "evaluate")
    builder.add_edge("evaluate", "review")
    builder.add_edge("review", "execute")
    builder.add_edge("execute", END)
    graph = builder.compile(name=f"{agent}_workflow")

    async def specialist(state: AgentState) -> dict[str, object]:
        result = await graph.ainvoke(state)
        return {key: result.get(key, []) for key in (
            "specialist_results", "tool_results", "resolved_entities", "proposed_actions"
        )}

    return specialist
