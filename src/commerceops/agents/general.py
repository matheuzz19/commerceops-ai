"""Deterministic, tool-free General worker."""

from commerceops.graph.state import AgentState, SpecialistResult


def general_response(state: AgentState) -> dict[str, object]:
    task = state["specialist_task"]
    query = task.query.casefold()

    if any(greeting in query for greeting in ("hello", "hi", "hey", "olá", "ola")):
        response = (
            "Hello! I can help with sales, inventory, and finance operations. "
            "What would you like to do?"
        )
    elif "help" in query or "ajuda" in query:
        response = (
            "I can help manage customers and orders, check inventory, and review "
            "financial transactions. Please describe the operation you need."
        )
    else:
        response = (
            "I need a little more detail before I can route this safely. "
            "Please clarify the business operation you want to perform."
        )

    result = SpecialistResult(
        task_index=state["task_index"],
        agent="general",
        query=task.query,
        response=response,
    )
    return {"specialist_results": [result]}
