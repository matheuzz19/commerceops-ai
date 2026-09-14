"""Structured multi-agent classification and dynamic LangGraph dispatch."""

from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Send
from pydantic import SecretStr

from commerceops.config import settings
from commerceops.graph.state import AgentState, AgentTask, RoutingPlan

ROUTER_SYSTEM_PROMPT = """You route commerce operations requests.
Classify every requested operation using this ownership map:
- sales: customers, product catalog search, and orders, including create, list, update, or cancel.
- inventory: stock levels and inventory movements.
- finance: revenue, expenses, transactions, and financial summaries.
- general: greetings, help, unsupported requests, or requests whose business domain is unknowable.

Split multi-domain requests into the smallest independent tasks.
Include every relevant specialist.
Missing names, IDs, dates, or other execution details do not make a request general; route it to the
owning specialist, which can clarify later. Never return general alongside another specialist.
Return at most one task per department. Do not invent identifiers or execute tools."""


class QueryClassifier(Protocol):
    """Boundary used to keep graph tests deterministic and model-independent."""

    def classify(self, query: str) -> Awaitable[RoutingPlan]: ...


class LangChainQueryClassifier:
    """LangChain structured-output classifier used by the production graph."""

    def __init__(self, model: BaseChatModel) -> None:
        self._router = model.with_structured_output(RoutingPlan, method="json_schema")

    async def classify(self, query: str) -> RoutingPlan:
        result = await self._router.ainvoke(
            [SystemMessage(content=ROUTER_SYSTEM_PROMPT), HumanMessage(content=query)]
        )
        return RoutingPlan.model_validate(result)


def create_default_classifier() -> LangChainQueryClassifier:
    """Build the configured router without binding any tools."""

    from langchain_openai import ChatOpenAI

    api_key = SecretStr(settings.openai_api_key) if settings.openai_api_key else None
    return LangChainQueryClassifier(
        ChatOpenAI(model=settings.openai_model, api_key=api_key)
    )


def _general_fallback(query: str, reason: str) -> RoutingPlan:
    return RoutingPlan(
        tasks=[AgentTask(agent="general", query=query, reason=reason)]
    )


def normalize_routing_plan(plan: RoutingPlan, query: str) -> RoutingPlan:
    """Enforce one task per agent and General's exclusive fallback semantics."""

    unique_tasks: list[AgentTask] = []
    seen_agents: set[str] = set()
    for task in plan.tasks:
        if task.agent in seen_agents:
            continue
        seen_agents.add(task.agent)
        unique_tasks.append(task)

    if not unique_tasks:
        return _general_fallback(query, "No actionable route was produced.")

    general_tasks = [task for task in unique_tasks if task.agent == "general"]
    if general_tasks:
        return RoutingPlan(tasks=[general_tasks[0]])
    return RoutingPlan(tasks=unique_tasks)


def make_route_request(
    classifier: QueryClassifier,
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    async def route_request(state: AgentState) -> dict[str, object]:
        message = state["normalized_message"]
        try:
            plan = normalize_routing_plan(
                await classifier.classify(message.content), message.content
            )
            return {"routing_plan": plan, "error": None}
        except Exception:
            fallback = _general_fallback(
                message.content, "The request needs clarification before routing."
            )
            return {"routing_plan": fallback, "error": "ROUTER_CLASSIFICATION_FAILED"}

    return route_request


def dispatch_specialists(state: AgentState) -> list[Send]:
    """Fan out the routing plan as isolated specialist tasks."""

    sends: list[Send] = []
    for index, task in enumerate(state["routing_plan"].tasks):
        payload: AgentState = {
            "tenant_id": state["tenant_id"],
            "user_id": state["user_id"],
            "session_id": state["session_id"],
            "specialist_task": task,
            "task_index": index,
        }
        sends.append(Send(cast(str, task.agent), payload))
    return sends
