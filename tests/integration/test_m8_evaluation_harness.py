from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from commerceops.domain.models import Customer, Tenant
from commerceops.evals.harness import run_case
from commerceops.evals.runner import load_cases


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dataset,index",
    [
        ("entity_resolution", 1),
        ("task_completion", 15),
        ("task_completion", 17),
        ("policy_violations", 16),
        ("task_completion", 18),
        ("task_completion", 19),
    ],
)
async def test_real_workflows_and_adversarial_cases_leave_no_fixture_data(
    session: Session,
    dataset: str,
    index: int,
) -> None:
    engine = session.get_bind()
    assert isinstance(engine, Engine)
    before = session.scalar(select(func.count()).select_from(Tenant))
    case = load_cases(Path("evals/datasets"))[dataset][index]
    result = await run_case(case, dataset, engine, live=False)
    assert result.task_completed
    assert result.tools_correct
    assert result.entities_correct
    assert result.hitl_correct
    assert not result.tenant_leakage
    assert not result.invalid_success_claim
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Tenant)) == before
    assert session.scalar(select(func.count()).select_from(Customer)) == 0


@pytest.mark.asyncio
async def test_wrong_reference_cannot_change_replay_actions(session: Session) -> None:
    engine = session.get_bind()
    assert isinstance(engine, Engine)
    case = load_cases(Path("evals/datasets"))["tool_selection"][4]
    case.reference.tools = ["create_transaction"]
    case.reference.effects["customers"] = 0
    result = await run_case(case, "tool_selection", engine, live=False)
    assert not result.tools_correct
    assert not result.task_completed
