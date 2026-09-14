"""Inventory specialist workflows with product resolution."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from commerceops.agents.planning import InventoryPlan, PlanProvider
from commerceops.agents.runtime import ToolClientFactory, verified_call
from commerceops.config import settings
from commerceops.graph.state import AgentState, ResolvedEntity, SpecialistResult
from commerceops.mcp.context import Specialist
from commerceops.mcp.tools.schemas import (
    InventoryLevelData,
    InventoryMovementListData,
    InventoryMovementResultData,
    ProductSearchData,
    ToolResult,
)


def _message(result: ToolResult) -> str:
    return result.error.message if result.error else "The Inventory operation failed."


def _finish(
    state: AgentState, response: str, records: list[dict[str, object]] | None = None,
    entities: list[ResolvedEntity] | None = None, error: str | None = None,
) -> dict[str, object]:
    task = state["specialist_task"]
    return {
        "specialist_results": [SpecialistResult(
            task_index=state["task_index"], agent="inventory", query=task.query,
            response=response, error=error,
        )],
        "tool_results": records or [], "resolved_entities": entities or [],
    }


def make_inventory_specialist(
    planner: PlanProvider[InventoryPlan], client_factory: ToolClientFactory
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    async def inventory_specialist(state: AgentState) -> dict[str, object]:
        try:
            tenant_id = UUID(state["tenant_id"])
            plan = await planner.plan(state["specialist_task"].query)
        except (ValueError, KeyError):
            return _finish(state, "The Inventory request context is invalid.",
                           error="INVALID_CONTEXT")
        except Exception:
            return _finish(state, "I could not understand the Inventory request safely.",
                           error="INVENTORY_PLANNING_FAILED")
        if plan.action == "clarify":
            return _finish(state, plan.clarification or "Please clarify the Inventory request.")
        client = client_factory(tenant_id, Specialist.INVENTORY)
        records: list[dict[str, object]] = []
        entities: list[ResolvedEntity] = []
        product_id: str | None = None
        if plan.product_query:
            data, result, record = await verified_call(client, "search_products", {
                "query": plan.product_query, "active_only": True,
            }, ProductSearchData)
            records.append(record)
            if not isinstance(data, ProductSearchData):
                return _finish(state, _message(result), records, error="TOOL_FAILED")
            exact = [product for product in data.products if (
                product.name.casefold() == plan.product_query.casefold()
                or product.sku.casefold() == plan.product_query.casefold()
            )]
            matches = exact or data.products
            if len(matches) != 1:
                text = "No matching product was found." if not matches else (
                    "Multiple products matched; please provide a more specific name or SKU."
                )
                return _finish(state, text, records)
            product = matches[0]
            product_id = str(product.id)
            entities.append(ResolvedEntity(
                entity_type="product", id=product_id, display_name=product.name,
                source_tool_call_id=result.audit_id,
            ))

        if plan.action == "get_level":
            if product_id is None:
                return _finish(state, "Please provide a product to check.", records, entities)
            data, result, record = await verified_call(
                client, "get_inventory_level", {"product_id": product_id}, InventoryLevelData
            )
            records.append(record)
            if not isinstance(data, InventoryLevelData):
                return _finish(state, _message(result), records, entities, "TOOL_FAILED")
            return _finish(state, f"Available quantity: {data.available_quantity}.",
                           records, entities)

        if plan.action == "list_movements":
            arguments = {"product_id": product_id} if product_id else {}
            data, result, record = await verified_call(
                client, "list_inventory_movements", arguments, InventoryMovementListData
            )
            records.append(record)
            if not isinstance(data, InventoryMovementListData):
                return _finish(state, _message(result), records, entities, "TOOL_FAILED")
            return _finish(state, f"Found {len(data.movements)} inventory movement(s).",
                           records, entities)

        if plan.action == "create_movement":
            if (
                product_id is None
                or plan.movement_type is None
                or plan.quantity is None
                or not plan.reason
            ):
                return _finish(
                    state,
                    "Please provide product, movement type, quantity, and reason.",
                    records,
                    entities,
                )
            if abs(plan.quantity) > settings.large_inventory_movement:
                return _finish(state, "This large inventory movement requires M6 approval.",
                               records, entities, "HITL_NOT_IMPLEMENTED")
            data, result, record = await verified_call(client, "create_inventory_movement", {
                "product_id": product_id, "movement_type": plan.movement_type.value,
                "quantity": plan.quantity, "reason": plan.reason,
            }, InventoryMovementResultData)
            records.append(record)
            if not isinstance(data, InventoryMovementResultData):
                return _finish(state, _message(result), records, entities, "TOOL_FAILED")
            return _finish(
                state,
                f"Inventory movement {data.movement.id} was created successfully.",
                records,
                entities,
            )
        return _finish(state, "The requested Inventory operation is not supported.", records,
                       entities)

    return inventory_specialist
