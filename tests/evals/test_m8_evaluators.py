from pathlib import Path

import pytest

from commerceops.evals.metrics import MINIMUM_CASES, summarize
from commerceops.evals.models import CaseResult
from commerceops.evals.runner import load_cases


def passing_results() -> list[CaseResult]:
    return [
        CaseResult(
            id=f"{dataset}-{index}",
            dataset=dataset,
            routing_correct=True,
            tools_correct=True,
            entities_correct=True,
            task_completed=True,
            latency_seconds=0.1,
        )
        for dataset, count in MINIMUM_CASES.items()
        for index in range(count)
    ]


def test_all_workflow_datasets_meet_minimums_and_have_unique_ids() -> None:
    datasets = load_cases(Path("evals/datasets"))
    for name, rows in datasets.items():
        assert len(rows) >= MINIMUM_CASES[name]
    assert len({row.id for rows in datasets.values() for row in rows}) == 90


@pytest.mark.parametrize(
    "field", ["forbidden_tool_call", "tenant_leakage", "invalid_success_claim"]
)
def test_one_safety_violation_fails_release_gate(field: str) -> None:
    results = passing_results()
    setattr(results[-1], field, True)
    report = summarize(results)
    assert not report["passed"]
    assert report["metrics"][field + "_rate"] > 0


def test_missing_dataset_and_execution_errors_fail_gate() -> None:
    results = passing_results()
    results[-1].error_code = "EVAL_EXECUTION_FAILED"
    assert not summarize(results)["passed"]
    assert not summarize(results[:-20])["passed"]


def test_missing_cost_is_unknown_instead_of_zero() -> None:
    report = summarize(passing_results())
    assert report["metrics"]["average_cost_per_request"] is None
    assert report["metrics"]["cost_coverage"] == 0


def test_routing_and_task_thresholds_are_enforced() -> None:
    results = passing_results()
    for row in results[:5]:
        row.routing_correct = False
    report = summarize(results)
    assert report["checks"]["routing_accuracy"] is False
    for row in results:
        if row.dataset == "task_completion":
            row.task_completed = False
    assert summarize(results)["checks"]["task_completion_rate"] is False


def test_one_specialist_success_cannot_validate_another_specialist_claim() -> None:
    from commerceops.evals.harness import invalid_success_claim
    from commerceops.graph.state import SpecialistResult

    state = {
        "specialist_results": [
            SpecialistResult(
                task_index=0, agent="sales", query="Synthetic", response="Created successfully"
            ),
            SpecialistResult(
                task_index=1, agent="finance", query="Synthetic", response="Recorded successfully"
            ),
        ],
        "tool_results": [{"tool_name": "create_customer", "result": {"ok": True}}],
    }
    assert invalid_success_claim(state, {"customers": 1, "transactions": 0})


def test_live_gates_keep_probability_thresholds_and_still_reject_hitl_failures() -> None:
    results = passing_results()
    next(row for row in results if row.dataset == "entity_resolution").entities_correct = False
    assert not summarize(results)["passed"]
    report = summarize(results, strict_references=False)
    assert report["passed"]
    assert not report["all_references_pass"]
    results[-1].hitl_correct = False
    assert not summarize(results, strict_references=False)["passed"]
