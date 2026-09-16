"""Sales specialist workflows with mandatory entity resolution."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from commerceops.agents.planning import PlanProvider, SalesPlan
from commerceops.agents.runtime import (
    ToolCaller,
    ToolClientFactory,
    create_tool_client,
    verified_call,
)
from commerceops.graph.policy import PolicyContext, propose_action, require_policy_approval
from commerceops.graph.state import AgentState, ProposedAction, ResolvedEntity, SpecialistResult
from commerceops.mcp.context import Specialist
from commerceops.mcp.tools.schemas import (
    CustomerResultData,
    CustomerSearchData,
    OrderListData,
    OrderResultData,
    ProductSearchData,
    ToolResult,
)


def _failure_message(result: ToolResult) -> str:
    return result.error.message if result.error else "The Sales operation could not be completed."


def _finish(
    state: AgentState,
    response: str,
    *,
    records: list[dict[str, object]] | None = None,
    entities: list[ResolvedEntity] | None = None,
    actions: list[ProposedAction] | None = None,
    error: str | None = None,
) -> dict[str, object]:
    task = state["specialist_task"]
    return {
        "specialist_results": [
            SpecialistResult(
                task_index=state["task_index"], agent="sales", query=task.query,
                response=response, error=error,
            )
        ],
        "tool_results": records or [],
        "resolved_entities": entities or [],
        "proposed_actions": actions or [],
    }


async def _resolve_customer(
    client: ToolCaller, query: str
) -> tuple[str | None, ResolvedEntity | None, dict[str, object], str | None]:
    data, result, record = await verified_call(
        client, "search_customers", {"query": query}, CustomerSearchData
    )
    if not isinstance(data, CustomerSearchData):
        return None, None, record, _failure_message(result)
    exact = [item for item in data.customers if item.name.casefold() == query.casefold()]
    matches = exact or data.customers
    if len(matches) != 1:
        message = "No matching customer was found." if not matches else (
            "Multiple customers matched; please provide a more specific customer name."
        )
        return None, None, record, message
    customer = matches[0]
    return str(customer.id), ResolvedEntity(
        entity_type="customer", id=str(customer.id), display_name=customer.name,
        source_tool_call_id=result.audit_id,
    ), record, None


async def _resolve_product(
    client: ToolCaller, query: str
) -> tuple[str | None, ResolvedEntity | None, dict[str, object], str | None]:
    data, result, record = await verified_call(
        client, "search_products", {"query": query, "active_only": True}, ProductSearchData
    )
    if not isinstance(data, ProductSearchData):
        return None, None, record, _failure_message(result)
    exact = [item for item in data.products if (
        item.name.casefold() == query.casefold() or item.sku.casefold() == query.casefold()
    )]
    matches = exact or data.products
    if len(matches) != 1:
        message = "No matching product was found." if not matches else (
            "Multiple products matched; please provide a more specific product name or SKU."
        )
        return None, None, record, message
    product = matches[0]
    return str(product.id), ResolvedEntity(
        entity_type="product", id=str(product.id), display_name=product.name,
        source_tool_call_id=result.audit_id,
    ), record, None


def make_sales_specialist(
    planner: PlanProvider[SalesPlan], client_factory: ToolClientFactory
) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
    async def sales_specialist(state: AgentState) -> dict[str, object]:
        task = state["specialist_task"]
        try:
            tenant_id = UUID(state["tenant_id"])
            plan = await planner.plan(task.query)
        except (ValueError, KeyError):
            return _finish(state, "The Sales request context is invalid.", error="INVALID_CONTEXT")
        except Exception:
            return _finish(state, "I could not understand the Sales request safely.",
                           error="SALES_PLANNING_FAILED")

        client = create_tool_client(client_factory, tenant_id, Specialist.SALES)
        records: list[dict[str, object]] = []
        entities: list[ResolvedEntity] = []
        if plan.action == "clarify":
            return _finish(state, plan.clarification or "Please clarify the Sales request.")

        if plan.action in {"search_customers", "search_products"}:
            if not plan.query:
                return _finish(state, "Please provide a name or search term.")
            schema = CustomerSearchData if plan.action == "search_customers" else ProductSearchData
            data, result, record = await verified_call(
                client, plan.action, {"query": plan.query}, schema
            )
            if data is None:
                return _finish(
                    state, _failure_message(result), records=[record], error="TOOL_FAILED"
                )
            if isinstance(data, CustomerSearchData):
                names = ", ".join(item.name for item in data.customers) or "none"
                return _finish(state, f"Matching customers: {names}.", records=[record])
            assert isinstance(data, ProductSearchData)
            names = ", ".join(item.name for item in data.products) or "none"
            return _finish(state, f"Matching products: {names}.", records=[record])

        if plan.action == "create_customer":
            if not plan.customer_name:
                return _finish(state, "Please provide the new customer's name.")
            customer_arguments: dict[str, object] = {
                "name": plan.customer_name, "email": plan.email, "phone": plan.phone,
            }
            action = propose_action("create_customer", customer_arguments)
            decision, approved = require_policy_approval(
                action, PolicyContext(str(tenant_id), Specialist.SALES)
            )
            if not decision.allowed:
                return _finish(state, decision.reason, actions=[action], error="POLICY_DENIED")
            if not approved:
                return _finish(
                    state, "The customer creation was rejected and was not executed.",
                    actions=[action], error="ACTION_REJECTED",
                )
            data, result, record = await verified_call(
                client, "create_customer", customer_arguments, CustomerResultData
            )
            if not isinstance(data, CustomerResultData):
                return _finish(
                    state, _failure_message(result), records=[record], actions=[action],
                    error="TOOL_FAILED"
                )
            return _finish(state, f"Customer {data.customer.name} was created successfully.",
                           records=[record], actions=[action])

        if plan.action == "list_orders":
            arguments: dict[str, object] = {}
            if plan.customer_query:
                customer_id, entity, record, error = await _resolve_customer(
                    client, plan.customer_query
                )
                records.append(record)
                if error or customer_id is None or entity is None:
                    return _finish(state, error or "Customer resolution failed.", records=records)
                arguments["customer_id"] = customer_id
                entities.append(entity)
            if plan.order_status:
                arguments["status"] = plan.order_status.value
            data, result, record = await verified_call(client, "list_orders", arguments,
                                                       OrderListData)
            records.append(record)
            if not isinstance(data, OrderListData):
                return _finish(state, _failure_message(result), records=records,
                               entities=entities, error="TOOL_FAILED")
            return _finish(state, f"Found {len(data.orders)} order(s).", records=records,
                           entities=entities)

        if plan.action == "create_order":
            if not plan.customer_query or not plan.items:
                return _finish(state, "Please provide a customer and at least one product item.")
            customer_id, customer, record, error = await _resolve_customer(
                client, plan.customer_query
            )
            records.append(record)
            if error or customer_id is None or customer is None:
                return _finish(state, error or "Customer resolution failed.", records=records)
            entities.append(customer)
            items: list[dict[str, object]] = []
            for item in plan.items:
                product_id, product, record, error = await _resolve_product(
                    client, item.product_query
                )
                records.append(record)
                if error or product_id is None or product is None:
                    return _finish(state, error or "Product resolution failed.", records=records,
                                   entities=entities)
                entities.append(product)
                items.append({"product_id": product_id, "quantity": item.quantity})
            create_order_arguments: dict[str, object] = {
                "customer_id": customer_id, "items": items,
            }
            action = propose_action("create_order", create_order_arguments)
            decision, approved = require_policy_approval(
                action,
                PolicyContext(str(tenant_id), Specialist.SALES, entities),
                proposed_write_count=1 + len(items),
            )
            if not decision.allowed:
                return _finish(
                    state, decision.reason, records=records, entities=entities,
                    actions=[action], error="POLICY_DENIED",
                )
            if not approved:
                return _finish(
                    state, "The order creation was rejected and was not executed.",
                    records=records, entities=entities, actions=[action],
                    error="ACTION_REJECTED",
                )
            data, result, record = await verified_call(
                client, "create_order", create_order_arguments, OrderResultData
            )
            records.append(record)
            if not isinstance(data, OrderResultData):
                return _finish(state, _failure_message(result), records=records,
                               entities=entities, actions=[action], error="TOOL_FAILED")
            return _finish(state, f"Order {data.order.id} was created successfully for "
                           f"{data.order.total_amount}.", records=records, entities=entities,
                           actions=[action])

        if plan.action == "update_order":
            if not plan.order_reference or not plan.order_status:
                return _finish(state, "Please provide the order and its requested status.")
            data, result, record = await verified_call(client, "list_orders", {}, OrderListData)
            records.append(record)
            if not isinstance(data, OrderListData):
                return _finish(state, _failure_message(result), records=records,
                               error="TOOL_FAILED")
            matches = [order for order in data.orders if str(order.id) == plan.order_reference]
            if len(matches) != 1:
                return _finish(state, "The order could not be resolved safely.", records=records)
            order = matches[0]
            entities.append(ResolvedEntity(
                entity_type="order", id=str(order.id), display_name=str(order.id),
                source_tool_call_id=result.audit_id,
            ))
            arguments = {"order_id": str(order.id), "status": plan.order_status.value}
            if plan.payment_status:
                arguments["payment_status"] = plan.payment_status.value
            action = propose_action("update_order", arguments)
            decision, approved = require_policy_approval(
                action, PolicyContext(str(tenant_id), Specialist.SALES, entities)
            )
            if not decision.allowed:
                return _finish(
                    state, decision.reason, records=records, entities=entities,
                    actions=[action], error="POLICY_DENIED",
                )
            if not approved:
                return _finish(
                    state, "The order update was rejected and was not executed.",
                    records=records, entities=entities, actions=[action],
                    error="ACTION_REJECTED",
                )
            updated, update_result, record = await verified_call(
                client, "update_order", arguments, OrderResultData
            )
            records.append(record)
            if not isinstance(updated, OrderResultData):
                return _finish(state, _failure_message(update_result), records=records,
                               entities=entities, actions=[action], error="TOOL_FAILED")
            return _finish(state, f"Order {updated.order.id} was updated successfully.",
                           records=records, entities=entities, actions=[action])

        return _finish(state, "The requested Sales operation is not supported.")

    return sales_specialist
