from commerceops.graph.routing import normalize_routing_plan
from commerceops.graph.state import AgentTask, RoutingPlan


def test_routing_plan_deduplicates_agents() -> None:
    plan = RoutingPlan(
        tasks=[
            AgentTask(agent="sales", query="Find customer", reason="Customer request"),
            AgentTask(agent="sales", query="Find order", reason="Order request"),
            AgentTask(agent="finance", query="Show revenue", reason="Finance request"),
        ]
    )

    normalized = normalize_routing_plan(plan, "combined request")

    assert [task.agent for task in normalized.tasks] == ["sales", "finance"]


def test_general_route_is_exclusive() -> None:
    plan = RoutingPlan(
        tasks=[
            AgentTask(agent="sales", query="Maybe order", reason="Possible sales request"),
            AgentTask(agent="general", query="Clarify", reason="Request is ambiguous"),
        ]
    )

    normalized = normalize_routing_plan(plan, "ambiguous request")

    assert [task.agent for task in normalized.tasks] == ["general"]
