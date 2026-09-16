"""M5 specialist runtime dependencies and verified MCP calls."""

from collections.abc import Awaitable, Callable, Mapping, Set
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, SecretStr

from commerceops.agents.planning import (
    FINANCE_PROMPT,
    INVENTORY_PROMPT,
    SALES_PROMPT,
    FinancePlan,
    InventoryPlan,
    LangChainPlanProvider,
    PlanProvider,
    SalesPlan,
)
from commerceops.config import settings
from commerceops.mcp.client import CommerceOpsMCPClient
from commerceops.mcp.context import Specialist, ToolRuntimeContext
from commerceops.mcp.tools.schemas import ToolResult


class ToolCaller(Protocol):
    def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> Awaitable[ToolResult]: ...


ToolClientFactory = Callable[..., ToolCaller]


@dataclass(frozen=True)
class SpecialistDependencies:
    sales_planner: PlanProvider[SalesPlan]
    inventory_planner: PlanProvider[InventoryPlan]
    finance_planner: PlanProvider[FinancePlan]
    client_factory: ToolClientFactory


def default_client_factory(
    tenant_id: UUID,
    specialist: Specialist,
    approval_grants: Set[str] = frozenset(),
) -> ToolCaller:
    return CommerceOpsMCPClient(
        ToolRuntimeContext(
            tenant_id=tenant_id,
            specialist=specialist,
            approval_grants=frozenset(approval_grants),
        )
    )


def create_tool_client(
    factory: ToolClientFactory,
    tenant_id: UUID,
    specialist: Specialist,
    approval_grants: frozenset[str] = frozenset(),
) -> ToolCaller:
    """Create a client, passing trusted grants only after an HITL approval."""

    if approval_grants:
        return factory(tenant_id, specialist, approval_grants)
    return factory(tenant_id, specialist)


def create_default_specialist_dependencies() -> SpecialistDependencies:
    from langchain_openai import ChatOpenAI

    api_key = SecretStr(settings.openai_api_key) if settings.openai_api_key else None
    model = ChatOpenAI(model=settings.openai_model, api_key=api_key)
    return SpecialistDependencies(
        sales_planner=LangChainPlanProvider(model, SalesPlan, SALES_PROMPT),
        inventory_planner=LangChainPlanProvider(model, InventoryPlan, INVENTORY_PROMPT),
        finance_planner=LangChainPlanProvider(model, FinancePlan, FINANCE_PROMPT),
        client_factory=default_client_factory,
    )


async def verified_call(
    client: ToolCaller,
    tool_name: str,
    arguments: Mapping[str, object],
    output_schema: type[BaseModel],
) -> tuple[BaseModel | None, ToolResult, dict[str, object]]:
    """Call MCP and validate tool-specific data before any success response."""

    result = await client.call_tool(tool_name, arguments)
    record: dict[str, object] = {
        "tool_name": tool_name,
        "result": result.model_dump(mode="json"),
    }
    if not result.ok or result.data is None:
        return None, result, record
    try:
        return output_schema.model_validate(result.data), result, record
    except ValueError:
        invalid = ToolResult.model_validate(
            {
                "ok": False,
                "data": None,
                "error": {
                    "code": "INVALID_TOOL_OUTPUT",
                    "message": "The tool returned an invalid response.",
                },
                "audit_id": result.audit_id,
            }
        )
        record["result"] = invalid.model_dump(mode="json")
        return None, invalid, record
