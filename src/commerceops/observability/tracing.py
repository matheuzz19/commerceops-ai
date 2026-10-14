"""Correlated graph/model observations and privacy-preserving LangSmith export."""

import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langsmith import Client, trace, tracing_context

from commerceops.config import settings
from commerceops.observability import metrics
from commerceops.observability.logging import IDENTITY, event

NODES = frozenset(
    {
        "normalize_message",
        "route_request",
        "sales",
        "inventory",
        "finance",
        "general",
        "evaluate_writes",
        "review_writes",
        "execute_write",
        "aggregate_results",
    }
)


def sanitize_run_ops(operations: Sequence[dict[str, Any]]) -> Sequence[dict[str, Any]]:
    """Preserve trace transport fields while stripping IO, exception text and model config."""
    allowed = {
        "request_id",
        "tenant_id",
        "session_id",
        "status",
        "graph_path",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "tool",
        "error_code",
        "policy_decisions",
        "route_agents",
        "duration_seconds",
        "llm_duration_seconds",
        "source_message_count",
        "approved",
    }
    cleaned = []
    for operation in operations:
        run = dict(operation)
        for key in ("inputs", "outputs", "serialized"):
            if key in run:
                run[key] = {}
        if run.get("error"):
            run["error"] = "EXECUTION_FAILED_OR_INTERRUPTED"
        run.pop("events", None)
        run.pop("attachments", None)
        if "extra" in run:
            extra = dict(run["extra"] or {})
            metadata = extra.get("metadata", {})
            extra["metadata"] = {key: value for key, value in metadata.items() if key in allowed}
            extra.pop("invocation_params", None)
            run["extra"] = extra
        cleaned.append(run)
    return cleaned


@lru_cache
def tracing_client() -> Client | None:
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return None
    # Hiding IO applies to all auto-generated graph, model and tool child runs.
    return Client(
        api_key=settings.langsmith_api_key,
        hide_inputs=True,
        hide_outputs=True,
        process_buffered_run_ops=sanitize_run_ops,
        run_ops_buffer_size=100,
    )


class ObservationCallback(BaseCallbackHandler):
    """One instance per invocation; no prompts or responses retained."""

    def __init__(self) -> None:
        self.nodes: list[str] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.usage_available = False
        self.llm_duration_seconds = 0.0
        self.policy_decisions: list[dict[str, Any]] = []
        self.route_agents: list[str] = []
        self._starts: dict[UUID, float] = {}
        self._node_runs: dict[UUID, str] = {}

    def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if node in NODES:
            self._node_runs[run_id] = node
            self.nodes.append(node)
            event("graph_node", node=node)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        node = self._node_runs.pop(run_id, None)
        if not isinstance(outputs, dict):
            return
        if node == "route_request" and outputs.get("routing_plan") is not None:
            self.route_agents = [task.agent for task in outputs["routing_plan"].tasks]
            event("route_decision", agents=self.route_agents)
        if node == "review_writes" and "writes_approved" in outputs:
            choice = "approved" if outputs["writes_approved"] else "rejected"
            metrics.HITL.labels(choice).inc()
            event("hitl_decision", approved=outputs["writes_approved"])
        if node == "evaluate_writes":
            self.policy_decisions.append(
                {
                    "requires_confirmation": outputs.get("requires_confirmation"),
                    "approved": outputs.get("writes_approved"),
                    "error_code": outputs.get("write_policy_error"),
                }
            )
            event(
                "policy_decision",
                requires_confirmation=outputs.get("requires_confirmation"),
                approved=outputs.get("writes_approved"),
                error_code=outputs.get("write_policy_error"),
            )

    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._starts[run_id] = time.perf_counter()

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._starts[run_id] = time.perf_counter()

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        elapsed = time.perf_counter() - self._starts.pop(run_id, time.perf_counter())
        self.llm_duration_seconds += max(0, elapsed)
        metrics.LLM_LATENCY.observe(max(0, elapsed))
        usage: dict[str, Any] = {}
        if response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
            usage = getattr(message, "usage_metadata", None) or {}
        if not usage:
            usage = (response.llm_output or {}).get("token_usage", {})
        if usage:
            self.usage_available = True
            incoming = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
            outgoing = int(usage.get("output_tokens", usage.get("completion_tokens", 0)))
            self.input_tokens += incoming
            self.output_tokens += outgoing
            metrics.TOKENS.labels("input").inc(incoming)
            metrics.TOKENS.labels("output").inc(outgoing)
        event(
            "llm_result",
            duration_seconds=max(0, elapsed),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._starts.pop(run_id, time.perf_counter())
        metrics.LLM_LATENCY.observe(max(0, time.perf_counter() - start))
        event("llm_error", error_code="LLM_CALL_FAILED")

    @property
    def cost_usd(self) -> float | None:
        if not self.usage_available:
            return None
        incoming = settings.llm_input_usd_per_million
        outgoing = settings.llm_output_usd_per_million
        if incoming is None or outgoing is None:
            return None
        return float((self.input_tokens * incoming + self.output_tokens * outgoing) / 1_000_000)


async def observed_invoke(
    graph: Any,
    payload: Any,
    *,
    config: dict[str, Any],
    trace_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    observer: ObservationCallback | None = None,
    tracing_enabled: bool | None = None,
) -> dict[str, Any]:
    request_id = trace_id or str(uuid4())
    raw = payload if isinstance(payload, dict) else {}
    identity = {
        "request_id": request_id,
        "tenant_id": tenant_id or raw.get("tenant_id", "unknown"),
        "session_id": session_id or raw.get("session_id", "unknown"),
    }
    token = IDENTITY.set(identity)
    callback = observer or ObservationCallback()
    active_config = {
        **config,
        "callbacks": [*config.get("callbacks", []), callback],
        "metadata": {**config.get("metadata", {}), **identity},
    }
    enabled = settings.langsmith_tracing if tracing_enabled is None else tracing_enabled
    started = time.perf_counter()
    prior_cost = callback.cost_usd or 0.0
    status = "failed"
    client = tracing_client() if enabled else None
    try:
        with (
            tracing_context(
                enabled=enabled and client is not None,
                client=client,
                project_name=settings.langsmith_project,
            ),
            trace(
                "commerceops.request",
                run_id=UUID(request_id),
                metadata=identity,
                inputs={},
                client=client,
            ) as run,
        ):
            event("graph_started")
            if not isinstance(payload, dict):
                decision_values = getattr(payload, "resume", {})
                decisions = (
                    list(decision_values.values()) if isinstance(decision_values, dict) else []
                )
                approved = bool(decisions) and all(
                    isinstance(item, dict) and item.get("approved") is True for item in decisions
                )
                event("hitl_resume", approved=approved)
                run.add_metadata({"approved": approved})
                metrics.HITL.labels("resume").inc()
            result: dict[str, Any] = await graph.ainvoke(payload, config=active_config)
            status = (
                "requires_confirmation"
                if result.get("__interrupt__")
                else ("failed" if result.get("error") else "completed")
            )
            if status == "requires_confirmation":
                metrics.HITL.labels("pause").inc()
                event("hitl_pause")
            run.add_metadata(
                {
                    "status": status,
                    "graph_path": callback.nodes,
                    "input_tokens": callback.input_tokens,
                    "output_tokens": callback.output_tokens,
                    "cost_usd": callback.cost_usd,
                    "policy_decisions": callback.policy_decisions,
                    "route_agents": callback.route_agents,
                    "duration_seconds": time.perf_counter() - started,
                    "llm_duration_seconds": callback.llm_duration_seconds,
                    "source_message_count": len(raw.get("source_message_ids", [])),
                }
            )
            return result
    except BaseException:
        event("graph_error", error_code="GRAPH_EXECUTION_FAILED")
        raise
    finally:
        elapsed = time.perf_counter() - started
        metrics.GRAPH_RUNS.labels(status).inc()
        metrics.GRAPH_LATENCY.observe(elapsed)
        if callback.cost_usd is not None:
            metrics.COST.inc(max(0, callback.cost_usd - prior_cost))
        event(
            "graph_finished",
            status=status,
            duration_seconds=elapsed,
            input_tokens=callback.input_tokens if callback.usage_available else None,
            output_tokens=callback.output_tokens if callback.usage_available else None,
            cost_usd=callback.cost_usd,
        )
        IDENTITY.reset(token)
