"""Shared behavior for M4 specialist skeleton workers."""

from commerceops.graph.state import AgentState, Department, SpecialistResult


def specialist_placeholder(state: AgentState, expected_agent: Department) -> dict[str, object]:
    """Return a safe result without executing MCP tools or business writes."""

    task = state["specialist_task"]
    if task.agent != expected_agent:
        result = SpecialistResult(
            task_index=state["task_index"],
            agent=expected_agent,
            query=task.query,
            response="This request could not be assigned safely.",
            error="SPECIALIST_ROUTE_MISMATCH",
        )
    else:
        result = SpecialistResult(
            task_index=state["task_index"],
            agent=expected_agent,
            query=task.query,
            response=(
                f"The {expected_agent} request was recognized. "
                "Business execution will be added in the specialist workflow milestone."
            ),
        )
    return {"specialist_results": [result]}
