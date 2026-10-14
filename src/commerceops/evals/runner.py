"""M8 CLI: replay for CI, live model evaluation for release evidence."""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from commerceops.agents.runtime import create_default_specialist_dependencies
from commerceops.config import settings
from commerceops.domain.models import Base
from commerceops.evals.harness import ReplayClassifier, run_case, run_routing_case
from commerceops.evals.metrics import MINIMUM_CASES, summarize
from commerceops.evals.models import CaseResult, EvalCase, Reference
from commerceops.evals.routing import load_routing_cases
from commerceops.graph.routing import create_default_classifier
from commerceops.observability.tracing import tracing_client


def load_cases(directory: Path) -> dict[str, list[EvalCase]]:
    datasets: dict[str, list[EvalCase]] = {}
    seen: set[str] = set()
    for name, minimum in MINIMUM_CASES.items():
        if name == "routing":
            continue
        rows: list[EvalCase] = []
        for line_number, line in enumerate(
            (directory / (name + ".jsonl")).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                row = EvalCase.model_validate_json(line)
            except ValueError as error:
                raise ValueError(f"Invalid {name} case at line {line_number}.") from error
            if row.id in seen:
                raise ValueError(f"Duplicate evaluation ID: {row.id}")
            seen.add(row.id)
            rows.append(row)
        if len(rows) < minimum:
            raise ValueError(f"{name} needs at least {minimum} cases.")
        datasets[name] = rows
    return datasets


def dataset_hashes(directory: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((directory / (name + ".jsonl")).read_bytes()).hexdigest()
        for name in MINIMUM_CASES
    }


async def run_evaluation(
    directory: Path,
    mode: str,
    *,
    concurrency: int = 1,
) -> dict[str, Any]:
    live = mode == "live"
    # Keep telemetry logs separate from the machine-readable evaluation report.
    import logging

    logging.getLogger("commerceops.events").setLevel(logging.WARNING)
    if live and not settings.openai_api_key:
        raise ValueError("Live evaluation requires OPENAI_API_KEY.")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise ValueError("Set TEST_DATABASE_URL to the isolated commerceops_test PostgreSQL DB.")
    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql") or parsed.database != "commerceops_test":
        raise ValueError("Evaluation requires PostgreSQL database commerceops_test.")
    datasets = load_cases(directory)
    routing_cases = load_routing_cases(directory / "routing.jsonl")
    if len(routing_cases) < MINIMUM_CASES["routing"]:
        raise ValueError("Routing needs at least 40 cases.")
    fixture_path = directory.parent / "fixtures" / "routing_plans.jsonl"
    replay_routes = [
        json.loads(line)
        for line in fixture_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not live and (
        [row["query"] for row in replay_routes] != [row.query for row in routing_cases]
    ):
        raise ValueError("Routing replay fixtures do not match dataset queries.")
    classifier = create_default_classifier() if live else None
    dependencies = create_default_specialist_dependencies() if live else None
    engine = create_engine(url, pool_pre_ping=True, pool_size=max(concurrency, 5))
    # Non-destructive schema creation only in the explicitly designated test database.
    Base.metadata.create_all(engine)
    semaphore = asyncio.Semaphore(concurrency)

    async def workflow(dataset: str, case: EvalCase) -> CaseResult:
        async with semaphore:
            try:
                result = await run_case(
                    case,
                    dataset,
                    engine,
                    live=live,
                    classifier=classifier,
                    live_dependencies=dependencies,
                )
            except Exception:
                result = CaseResult(
                    id=case.id,
                    dataset=dataset,
                    routing_correct=False,
                    tools_correct=False,
                    entities_correct=False,
                    task_completed=False,
                    hitl_correct=False,
                    latency_seconds=0,
                    error_code="EVAL_EXECUTION_FAILED",
                )
            print(
                json.dumps(
                    {"case": result.id, "dataset": dataset, "completed": result.task_completed}
                ),
                flush=True,
            )
            return result

    async def routing(index: int) -> CaseResult:
        async with semaphore:
            row = routing_cases[index]
            case_id = f"routing-{index + 1:02d}"
            replay_case = EvalCase(
                id=case_id,
                query=row.query,
                replay_agents=replay_routes[index]["agents"],
                reference=Reference(agents=list(row.expected_agents)),
            )
            try:
                return await run_routing_case(
                    case_id,
                    row.query,
                    set(row.expected_agents),
                    classifier or ReplayClassifier(replay_case),
                    live=live,
                )
            except Exception:
                return CaseResult(
                    id=case_id,
                    dataset="routing",
                    routing_correct=False,
                    tools_correct=False,
                    entities_correct=False,
                    task_completed=False,
                    latency_seconds=0,
                    error_code="EVAL_EXECUTION_FAILED",
                )

    try:
        results = await asyncio.gather(
            *(routing(index) for index in range(len(routing_cases))),
            *(workflow(name, case) for name, rows in datasets.items() for case in rows),
        )
    finally:
        engine.dispose()
        client = tracing_client() if live else None
        if client is not None:
            await asyncio.to_thread(client.flush, timeout=30)
    report = summarize(results, strict_references=not live)
    report.update(
        {
            "mode": mode,
            "model_tested": live,
            "model": settings.openai_model if live else None,
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset_sha256": dataset_hashes(directory),
            "versions": {
                name: version(name) for name in ("langgraph", "langsmith", "langchain-openai")
            },
            "pricing_usd_per_million": {
                "input": str(settings.llm_input_usd_per_million)
                if (settings.llm_input_usd_per_million is not None)
                else None,
                "output": str(settings.llm_output_usd_per_million)
                if (settings.llm_output_usd_per_million is not None)
                else None,
            },
            "cases": [row.model_dump() for row in results],
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("replay", "live"), default="replay")
    parser.add_argument("--datasets", type=Path, default=Path("evals/datasets"))
    parser.add_argument("--output", type=Path, default=Path("evals/reports/latest.json"))
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 8:
        parser.error("--concurrency must be between 1 and 8.")
    try:
        report = asyncio.run(run_evaluation(args.datasets, args.mode, concurrency=args.concurrency))
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps({key: value for key, value in report.items() if key != "cases"}, sort_keys=True)
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
