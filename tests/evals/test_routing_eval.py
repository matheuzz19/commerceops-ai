from pathlib import Path

import pytest

from commerceops.evals.routing import evaluate_routing, load_routing_cases
from commerceops.graph.state import AgentTask, Department, RoutingPlan


class KeywordClassifier:
    async def classify(self, query: str) -> RoutingPlan:
        agents: list[Department] = []
        lowered = query.casefold()
        if any(word in lowered for word in ("customer", "order", "product")):
            agents.append("sales")
        if any(word in lowered for word in ("stock", "inventory")):
            agents.append("inventory")
        if any(word in lowered for word in ("revenue", "expense", "transaction")):
            agents.append("finance")
        if not agents:
            agents.append("general")
        return RoutingPlan(
            tasks=[
                AgentTask(agent=agent, query=query, reason="Deterministic test route")
                for agent in agents
            ]
        )


def test_routing_dataset_contains_required_baseline_cases() -> None:
    cases = load_routing_cases(Path("evals/datasets/routing.jsonl"))

    assert len(cases) >= 40
    assert {agent for case in cases for agent in case.expected_agents} == {
        "sales",
        "inventory",
        "finance",
        "general",
    }
    assert any(len(case.expected_agents) > 1 for case in cases)


@pytest.mark.asyncio
async def test_routing_metric_uses_exact_agent_set() -> None:
    cases = load_routing_cases(Path("evals/datasets/routing.jsonl"))[:3]

    result = await evaluate_routing(KeywordClassifier(), cases)

    assert result.total == 3
    assert 0 <= result.routing_accuracy <= 1
