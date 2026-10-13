"""Finance specialist workflows."""

from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from commerceops.agents.planning import FinancePlan, PlanProvider
from commerceops.agents.runtime import ToolClientFactory, create_tool_client, verified_call
from commerceops.agents.workflow import prepare_write, standalone_specialist
from commerceops.config import settings
from commerceops.graph.policy import propose_action
from commerceops.graph.state import AgentState, ProposedAction, SpecialistResult
from commerceops.mcp.context import Specialist
from commerceops.mcp.tools.schemas import (
    FinancialSummaryData,
    ToolResult,
    TransactionListData,
)


def _finish(
    state: AgentState, response: str, records: list[dict[str, object]] | None = None,
    error: str | None = None,
    actions: list[ProposedAction] | None = None,
) -> dict[str, object]:
    task = state["specialist_task"]
    return {"specialist_results": [SpecialistResult(
        task_index=state["task_index"], agent="finance", query=task.query,
        response=response, error=error,
    )], "tool_results": records or [], "resolved_entities": [],
        "proposed_actions": actions or []}


def _message(result: ToolResult) -> str:
    return result.error.message if result.error else "The Finance operation failed."


def _resolve_period(plan: FinancePlan) -> tuple[date, date] | None:
    if plan.period_start is not None and plan.period_end is not None:
        return plan.period_start, plan.period_end
    if plan.relative_period is None:
        return None
    today = datetime.now(ZoneInfo(settings.default_tenant_timezone)).date()
    current_start = today.replace(day=1)
    if plan.relative_period == "current_month":
        next_month = (current_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return current_start, next_month - timedelta(days=1)
    previous_end = current_start - timedelta(days=1)
    return previous_end.replace(day=1), previous_end


def make_finance_preparer(
    planner: PlanProvider[FinancePlan], client_factory: ToolClientFactory
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    async def finance_specialist(state: AgentState) -> dict[str, object]:
        try:
            tenant_id = UUID(state["tenant_id"])
            plan = await planner.plan(state["specialist_task"].query)
        except (ValueError, KeyError):
            return _finish(
                state, "The Finance request context is invalid.", error="INVALID_CONTEXT"
            )
        except Exception:
            return _finish(state, "I could not understand the Finance request safely.",
                           error="FINANCE_PLANNING_FAILED")
        if plan.action == "clarify":
            return _finish(state, plan.clarification or "Please clarify the Finance request.")
        client = create_tool_client(client_factory, tenant_id, Specialist.FINANCE)

        if plan.action == "summary":
            period = _resolve_period(plan)
            if period is None:
                return _finish(state, "Please provide an explicit financial date range.")
            period_start, period_end = period
            data, result, record = await verified_call(client, "get_financial_summary", {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            }, FinancialSummaryData)
            if not isinstance(data, FinancialSummaryData):
                return _finish(state, _message(result), [record], "TOOL_FAILED")
            return _finish(state, f"Revenue: {data.revenue}; expenses: {data.expenses}; "
                           f"net: {data.net}.", [record])

        if plan.action == "list_transactions":
            arguments: dict[str, object] = {}
            if plan.transaction_type:
                arguments["type"] = plan.transaction_type.value
            if plan.transaction_status:
                arguments["status"] = plan.transaction_status.value
            data, result, record = await verified_call(
                client, "list_transactions", arguments, TransactionListData
            )
            if not isinstance(data, TransactionListData):
                return _finish(state, _message(result), [record], "TOOL_FAILED")
            return _finish(state, f"Found {len(data.transactions)} transaction(s).", [record])

        if plan.action == "create_expense":
            if plan.amount is None or plan.amount <= 0 or not plan.description:
                return _finish(state, "Please provide a positive amount and expense description.")
            arguments = {
                "type": "EXPENSE", "amount": str(plan.amount),
                "description": plan.description, "order_id": None,
            }
            action = propose_action("create_transaction", arguments)
            return prepare_write(state, action)

        return _finish(state, "The requested Finance operation is not supported.")

    return finance_specialist


def make_finance_specialist(
    planner: PlanProvider[FinancePlan], client_factory: ToolClientFactory
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    return standalone_specialist(
        make_finance_preparer(planner, client_factory), client_factory, "finance"
    )
