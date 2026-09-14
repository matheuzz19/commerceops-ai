"""Focused M4 routing evaluation; broader agent metrics remain in M8."""

import argparse
import asyncio
import json
from collections.abc import Iterable
from pathlib import Path

from langsmith import Client, tracing_context
from pydantic import BaseModel, Field

from commerceops.config import settings
from commerceops.graph.routing import (
    QueryClassifier,
    create_default_classifier,
    normalize_routing_plan,
)
from commerceops.graph.state import Department


class RoutingEvalCase(BaseModel):
    query: str = Field(min_length=1)
    expected_agents: set[Department] = Field(min_length=1)


class RoutingEvalResult(BaseModel):
    total: int
    correct: int
    routing_accuracy: float


def load_routing_cases(path: Path) -> list[RoutingEvalCase]:
    cases: list[RoutingEvalCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(RoutingEvalCase.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Invalid routing case at line {line_number}.") from exc
    if not cases:
        raise ValueError("Routing evaluation dataset is empty.")
    return cases


async def evaluate_routing(
    classifier: QueryClassifier, cases: Iterable[RoutingEvalCase]
) -> RoutingEvalResult:
    case_list = list(cases)
    correct = 0
    for case in case_list:
        plan = normalize_routing_plan(await classifier.classify(case.query), case.query)
        actual_agents = {task.agent for task in plan.tasks}
        if actual_agents == case.expected_agents:
            correct += 1
    total = len(case_list)
    return RoutingEvalResult(
        total=total,
        correct=correct,
        routing_accuracy=correct / total if total else 0.0,
    )


async def _run(path: Path) -> int:
    langsmith_client = (
        Client(api_key=settings.langsmith_api_key) if settings.langsmith_api_key else None
    )
    with tracing_context(
        client=langsmith_client,
        project_name=settings.langsmith_project,
        enabled=settings.langsmith_tracing,
        tags=["m4", "routing-baseline"],
        metadata={"dataset": path.name},
    ):
        result = await evaluate_routing(
            create_default_classifier(), load_routing_cases(path)
        )
    if langsmith_client is not None:
        langsmith_client.flush(timeout=30)
    print(json.dumps(result.model_dump(), sort_keys=True))
    return 0 if result.routing_accuracy >= 0.90 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the M4 live-model routing baseline.")
    parser.add_argument(
        "dataset", type=Path, nargs="?", default=Path("evals/datasets/routing.jsonl")
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.dataset))


if __name__ == "__main__":
    raise SystemExit(main())
