from collections.abc import Awaitable

import pytest

from commerceops.agents.planning import FinancePlan, InventoryPlan, SalesPlan
from commerceops.agents.runtime import SpecialistDependencies
from commerceops.agents.supervisor.graph import create_supervisor_graph
from commerceops.graph.state import AgentState, AgentTask, RoutingPlan
from commerceops.mcp.tools.schemas import ToolResult


class FixedClassifier:
    def __init__(self, plan: RoutingPlan) -> None:
        self.plan = plan

    async def classify(self, query: str) -> RoutingPlan:
        return self.plan


class FailingClassifier:
    def classify(self, query: str) -> Awaitable[RoutingPlan]:
        raise RuntimeError("model unavailable")


class FixedPlanner:
    def __init__(self, plan: SalesPlan | InventoryPlan | FinancePlan) -> None:
        self.value = plan

    async def plan(self, query: str) -> SalesPlan | InventoryPlan | FinancePlan:
        return self.value


class NoToolClient:
    async def call_tool(self, tool_name: str, arguments: object) -> ToolResult:
        raise AssertionError("M4 routing tests must not call tools")


def specialist_dependencies() -> SpecialistDependencies:
    return SpecialistDependencies(
        sales_planner=FixedPlanner(SalesPlan(action="clarify")),  # type: ignore[arg-type]
        inventory_planner=FixedPlanner(InventoryPlan(action="clarify")),  # type: ignore[arg-type]
        finance_planner=FixedPlanner(FinancePlan(action="clarify")),  # type: ignore[arg-type]
        client_factory=lambda tenant_id, specialist: NoToolClient(),
    )


def graph_input(content: str = "request") -> AgentState:
    return {
        "tenant_id": "tenant-one",
        "user_id": "user-one",
        "session_id": "session-one",
        "message_id": "message-one",
        "content": content,
        "content_type": "text",
    }


@pytest.mark.asyncio
async def test_single_domain_request_reaches_one_specialist() -> None:
    classifier = FixedClassifier(
        RoutingPlan(
            tasks=[AgentTask(agent="inventory", query="Check keyboard stock", reason="Stock")]
        )
    )
    graph = create_supervisor_graph(classifier, specialist_dependencies())

    events = [event async for event in graph.astream(graph_input(), stream_mode="updates")]
    visited = {node for event in events for node in event}

    assert "inventory" in visited
    assert not {"sales", "finance", "general"} & visited
    assert "aggregate_results" in visited


@pytest.mark.asyncio
async def test_multi_domain_request_fans_out_and_aggregates_in_task_order() -> None:
    classifier = FixedClassifier(
        RoutingPlan(
            tasks=[
                AgentTask(agent="finance", query="Show revenue", reason="Financial summary"),
                AgentTask(agent="inventory", query="Show keyboard stock", reason="Stock lookup"),
            ]
        )
    )
    graph = create_supervisor_graph(classifier, specialist_dependencies())

    result = await graph.ainvoke(graph_input("Show revenue and keyboard stock"))

    assert [item.agent for item in result["specialist_results"]] == ["finance", "inventory"]
    assert result["final_response"].index("Finance:") < result["final_response"].index(
        "Inventory:"
    )
    assert result["tool_results"] == []


@pytest.mark.asyncio
async def test_sales_and_inventory_updates_fan_out_without_executing_writes() -> None:
    classifier = FixedClassifier(
        RoutingPlan(
            tasks=[
                AgentTask(
                    agent="sales",
                    query="Confirm order ORD-100",
                    reason="Order status belongs to Sales",
                ),
                AgentTask(
                    agent="inventory",
                    query="Remove two keyboards from stock",
                    reason="Stock movement belongs to Inventory",
                ),
            ]
        )
    )
    graph = create_supervisor_graph(classifier, specialist_dependencies())

    events = [
        event
        async for event in graph.astream(
            graph_input("Confirm order ORD-100 and remove two keyboards from inventory"),
            stream_mode="updates",
        )
    ]
    visited = {node for event in events for node in event}
    result = await graph.ainvoke(
        graph_input("Confirm order ORD-100 and remove two keyboards from inventory")
    )

    assert {"sales", "inventory"} <= visited
    assert not {"finance", "general"} & visited
    assert [item.agent for item in result["specialist_results"]] == [
        "sales",
        "inventory",
    ]
    assert result["tool_results"] == []
    assert result["proposed_actions"] == []


@pytest.mark.asyncio
async def test_ambiguous_plan_dispatches_general_only() -> None:
    classifier = FixedClassifier(
        RoutingPlan(
            tasks=[
                AgentTask(agent="sales", query="Maybe create it", reason="Possible order"),
                AgentTask(agent="general", query="Clarify request", reason="Ambiguous"),
            ]
        )
    )
    graph = create_supervisor_graph(classifier, specialist_dependencies())

    events = [event async for event in graph.astream(graph_input(), stream_mode="updates")]
    visited = {node for event in events for node in event}

    assert "general" in visited
    assert not {"sales", "inventory", "finance"} & visited


@pytest.mark.asyncio
async def test_router_failure_recovers_through_general() -> None:
    graph = create_supervisor_graph(FailingClassifier(), specialist_dependencies())

    result = await graph.ainvoke(graph_input("unclear"))

    assert result["routing_plan"].tasks[0].agent == "general"
    assert result["error"] == "ROUTER_CLASSIFICATION_FAILED"
    assert result["final_response"] is not None
