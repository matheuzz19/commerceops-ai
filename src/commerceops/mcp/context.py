"""Trusted runtime identity used at the MCP authorization boundary."""

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Specialist(StrEnum):
    SALES = "sales"
    INVENTORY = "inventory"
    FINANCE = "finance"
    GENERAL = "general"


class ToolRuntimeContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    specialist: Specialist
    approval_grants: frozenset[str] = frozenset()


class RuntimeContextProvider(Protocol):
    def __call__(self) -> ToolRuntimeContext | None: ...


class FixedRuntimeContextProvider:
    """Inject identity from trusted application state, never tool arguments."""

    def __init__(self, context: ToolRuntimeContext | None) -> None:
        self._context = context

    def __call__(self) -> ToolRuntimeContext | None:
        return self._context
