"""CommerceOps M4 router-worker supervisor graph."""

from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from commerceops.agents.finance.graph import make_finance_preparer
from commerceops.agents.general import general_response
from commerceops.agents.inventory.graph import make_inventory_preparer
from commerceops.agents.runtime import (
    SpecialistDependencies,
    create_default_specialist_dependencies,
)
from commerceops.agents.sales.graph import make_sales_preparer
from commerceops.agents.supervisor.nodes import aggregate_results, normalize_message
from commerceops.agents.workflow import (
    dispatch_writes,
    evaluate_writes,
    make_execute_writes,
    review_writes,
)
from commerceops.graph.routing import (
    QueryClassifier,
    create_default_classifier,
    dispatch_specialists,
    make_route_request,
)
from commerceops.graph.state import AgentState


def create_supervisor_graph(
    classifier: QueryClassifier | None = None,
    specialist_dependencies: SpecialistDependencies | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the graph, optionally injecting a deterministic test classifier."""

    active_classifier = classifier or create_default_classifier()
    dependencies = specialist_dependencies or create_default_specialist_dependencies()
    builder = StateGraph(AgentState)
    builder.add_node("normalize_message", normalize_message)
    # LangGraph's current overloads infer ``Never`` for an injected async node
    # against a total=False TypedDict, although it is valid at runtime.
    builder.add_node("route_request", cast(Any, make_route_request(active_classifier)))
    builder.add_node(
        "sales",
        cast(Any, make_sales_preparer(dependencies.sales_planner, dependencies.client_factory)),
    )
    builder.add_node(
        "inventory",
        cast(
            Any,
            make_inventory_preparer(
                dependencies.inventory_planner, dependencies.client_factory
            ),
        ),
    )
    builder.add_node(
        "finance",
        cast(
            Any,
            make_finance_preparer(dependencies.finance_planner, dependencies.client_factory),
        ),
    )
    builder.add_node("general", general_response)
    builder.add_node("evaluate_writes", evaluate_writes)
    builder.add_node("review_writes", review_writes)
    builder.add_node("execute_write", cast(Any, make_execute_writes(dependencies.client_factory)))
    builder.add_node("aggregate_results", aggregate_results)

    builder.add_edge(START, "normalize_message")
    builder.add_edge("normalize_message", "route_request")
    builder.add_conditional_edges("route_request", dispatch_specialists)
    for specialist in ("sales", "inventory", "finance", "general"):
        builder.add_edge(specialist, "evaluate_writes")
    builder.add_edge("evaluate_writes", "review_writes")
    builder.add_conditional_edges("review_writes", dispatch_writes)
    builder.add_edge("execute_write", "aggregate_results")
    builder.add_edge("aggregate_results", END)
    return builder.compile(checkpointer=checkpointer)
