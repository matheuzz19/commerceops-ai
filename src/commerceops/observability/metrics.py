"""Process-local Prometheus collectors with bounded, non-identifying labels."""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "commerceops_http_requests", "HTTP responses", ["route", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "commerceops_http_duration_seconds", "HTTP latency", ["route"], registry=REGISTRY
)
GRAPH_RUNS = Counter("commerceops_graph_runs", "Graph invocations", ["status"], registry=REGISTRY)
GRAPH_LATENCY = Histogram(
    "commerceops_graph_duration_seconds",
    "Graph latency",
    buckets=(0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
    registry=REGISTRY,
)
TOOL_CALLS = Counter(
    "commerceops_tool_calls", "Verified tool outcomes", ["tool", "status"], registry=REGISTRY
)
TOOL_LATENCY = Histogram(
    "commerceops_tool_duration_seconds", "Tool latency", ["tool"], registry=REGISTRY
)
LLM_LATENCY = Histogram("commerceops_llm_duration_seconds", "Model latency", registry=REGISTRY)
TOKENS = Counter("commerceops_llm_tokens", "Reported tokens", ["direction"], registry=REGISTRY)
COST = Counter(
    "commerceops_estimated_cost_usd", "Cost using configured token prices", registry=REGISTRY
)
HITL = Counter("commerceops_hitl_events", "Approval lifecycle events", ["event"], registry=REGISTRY)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)
