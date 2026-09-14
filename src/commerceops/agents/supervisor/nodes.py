"""Deterministic supervisor nodes shared by graph construction and tests."""

from datetime import UTC, datetime

from commerceops.graph.state import AgentState, NormalizedMessage


def normalize_message(state: AgentState) -> dict[str, object]:
    """Validate raw graph input and establish a normalized trusted message."""

    message = NormalizedMessage(
        tenant_id=state["tenant_id"].strip(),
        user_id=state["user_id"].strip(),
        session_id=state["session_id"].strip(),
        message_id=state["message_id"].strip(),
        content=state["content"].strip(),
        content_type=state.get("content_type", "text"),
        timestamp=state.get("timestamp", datetime.now(UTC)),
    )
    return {
        "tenant_id": message.tenant_id,
        "user_id": message.user_id,
        "session_id": message.session_id,
        "normalized_message": message,
        "specialist_results": [],
        "resolved_entities": [],
        "tool_results": [],
        "final_response": None,
        "error": None,
    }


def aggregate_results(state: AgentState) -> dict[str, object]:
    """Combine parallel worker results in original router-task order."""

    results = sorted(state.get("specialist_results", []), key=lambda item: item.task_index)
    if not results:
        return {
            "final_response": "I could not route this request safely. Please try again.",
            "error": "NO_SPECIALIST_RESULTS",
        }

    if len(results) == 1:
        final_response = results[0].response
    else:
        sections = [f"{result.agent.title()}: {result.response}" for result in results]
        final_response = "\n\n".join(sections)

    worker_errors = [result.error for result in results if result.error]
    return {
        "final_response": final_response,
        "error": ",".join(worker_errors) if worker_errors else state.get("error"),
    }
