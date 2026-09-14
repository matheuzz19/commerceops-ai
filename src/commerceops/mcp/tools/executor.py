"""Authorized MCP tool dispatch backed by deterministic application services."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from commerceops.db.session import SessionLocal
from commerceops.domain.invariants import DomainError
from commerceops.domain.models import Customer, InventoryMovement, Order, Product, Transaction
from commerceops.mcp.authorization import is_authorized
from commerceops.mcp.context import RuntimeContextProvider
from commerceops.mcp.tools.schemas import (
    CreateCustomerInput,
    CreateInventoryMovementInput,
    CreateOrderInput,
    CreateTransactionInput,
    CustomerData,
    CustomerResultData,
    CustomerSearchData,
    FinancialSummaryData,
    GetFinancialSummaryInput,
    GetInventoryLevelInput,
    InventoryLevelData,
    InventoryMovementData,
    InventoryMovementListData,
    InventoryMovementResultData,
    ListInventoryMovementsInput,
    ListOrdersInput,
    ListTransactionsInput,
    OrderData,
    OrderItemData,
    OrderListData,
    OrderResultData,
    ProductData,
    ProductSearchData,
    SearchCustomersInput,
    SearchProductsInput,
    ToolErrorData,
    ToolResult,
    TransactionData,
    TransactionListData,
    TransactionResultData,
    UpdateOrderInput,
)
from commerceops.services import (
    CustomerService,
    FinanceService,
    InventoryService,
    OrderItemRequest,
    OrderService,
    ProductService,
)

SessionFactory = Callable[[], AbstractContextManager[Session]]


@contextmanager
def default_session_factory() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class ToolExecutor:
    def __init__(
        self,
        context_provider: RuntimeContextProvider,
        session_factory: SessionFactory = default_session_factory,
    ) -> None:
        self._context_provider = context_provider
        self._session_factory = session_factory

    def execute(self, tool_name: str, arguments: Mapping[str, object]) -> ToolResult:
        audit_id = str(uuid4())
        runtime = self._context_provider()
        if runtime is None:
            return _failure(
                audit_id,
                "CONTEXT_UNAVAILABLE",
                "Trusted runtime context is unavailable.",
            )
        if not is_authorized(runtime.specialist, tool_name):
            return _failure(
                audit_id,
                "TOOL_UNAUTHORIZED",
                "This specialist is not authorized to use that tool.",
            )
        if "tenant_id" in arguments:
            return _failure(audit_id, "INVALID_INPUT", "Tool input is invalid.")

        try:
            with self._session_factory() as session:
                try:
                    data = self._dispatch(session, runtime.tenant_id, tool_name, arguments)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            return _success(audit_id, data)
        except ValidationError:
            return _failure(audit_id, "INVALID_INPUT", "Tool input is invalid.")
        except DomainError as error:
            return _failure(audit_id, error.code, error.message)
        except ValueError:
            return _failure(audit_id, "INVALID_INPUT", "Tool input is invalid.")
        except SQLAlchemyError:
            return _failure(
                audit_id, "PERSISTENCE_ERROR", "The operation could not be completed."
            )

    def _dispatch(
        self,
        session: Session,
        tenant_id: UUID,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> BaseModel:
        if tool_name == "search_customers":
            search_customers_input = SearchCustomersInput.model_validate(arguments)
            customers = CustomerService(session).search(
                tenant_id, search_customers_input.query, search_customers_input.limit
            )
            return CustomerSearchData(customers=[_customer_data(item) for item in customers])
        if tool_name == "create_customer":
            create_customer_input = CreateCustomerInput.model_validate(arguments)
            customer = CustomerService(session).create(
                tenant_id,
                create_customer_input.name,
                create_customer_input.email,
                create_customer_input.phone,
            )
            return CustomerResultData(customer=_customer_data(customer))
        if tool_name == "search_products":
            search_products_input = SearchProductsInput.model_validate(arguments)
            products = ProductService(session).search(
                tenant_id,
                search_products_input.query,
                search_products_input.active_only,
                search_products_input.limit,
            )
            return ProductSearchData(products=[_product_data(item) for item in products])
        if tool_name == "list_orders":
            list_orders_input = ListOrdersInput.model_validate(arguments)
            orders = OrderService(session).list(
                tenant_id,
                list_orders_input.customer_id,
                list_orders_input.status,
                list_orders_input.limit,
            )
            return OrderListData(orders=[_order_data(item) for item in orders])
        if tool_name == "create_order":
            create_order_input = CreateOrderInput.model_validate(arguments)
            order = OrderService(session).create(
                tenant_id,
                create_order_input.customer_id,
                [
                    OrderItemRequest(item.product_id, item.quantity)
                    for item in create_order_input.items
                ],
            )
            return OrderResultData(order=_order_data(order))
        if tool_name == "update_order":
            update_order_input = UpdateOrderInput.model_validate(arguments)
            order = OrderService(session).update(
                tenant_id,
                update_order_input.order_id,
                update_order_input.status,
                update_order_input.payment_status,
            )
            return OrderResultData(order=_order_data(order))
        if tool_name == "get_inventory_level":
            inventory_level_input = GetInventoryLevelInput.model_validate(arguments)
            available = InventoryService(session).get_level(
                tenant_id, inventory_level_input.product_id
            )
            return InventoryLevelData(
                product_id=inventory_level_input.product_id,
                available_quantity=available,
            )
        if tool_name == "list_inventory_movements":
            list_movements_input = ListInventoryMovementsInput.model_validate(arguments)
            movements = InventoryService(session).list_movements(
                tenant_id, list_movements_input.product_id, list_movements_input.limit
            )
            return InventoryMovementListData(
                movements=[_movement_data(item) for item in movements]
            )
        if tool_name == "create_inventory_movement":
            create_movement_input = CreateInventoryMovementInput.model_validate(arguments)
            movement = InventoryService(session).create_movement(
                tenant_id,
                create_movement_input.product_id,
                create_movement_input.movement_type,
                create_movement_input.quantity,
                create_movement_input.reason,
            )
            return InventoryMovementResultData(movement=_movement_data(movement))
        if tool_name == "get_financial_summary":
            summary_input = GetFinancialSummaryInput.model_validate(arguments)
            summary = FinanceService(session).summary(
                tenant_id, summary_input.period_start, summary_input.period_end
            )
            return FinancialSummaryData(
                revenue=summary.revenue,
                expenses=summary.expenses,
                net=summary.net,
                transaction_count=summary.transaction_count,
            )
        if tool_name == "list_transactions":
            list_transactions_input = ListTransactionsInput.model_validate(arguments)
            transactions = FinanceService(session).list_transactions(
                tenant_id,
                list_transactions_input.type,
                list_transactions_input.status,
                list_transactions_input.limit,
            )
            return TransactionListData(
                transactions=[_transaction_data(item) for item in transactions]
            )
        if tool_name == "create_transaction":
            create_transaction_input = CreateTransactionInput.model_validate(arguments)
            transaction = FinanceService(session).record_transaction(
                tenant_id,
                create_transaction_input.type,
                create_transaction_input.amount,
                create_transaction_input.description,
                create_transaction_input.order_id,
            )
            return TransactionResultData(transaction=_transaction_data(transaction))
        raise DomainError("TOOL_NOT_FOUND", "The requested tool does not exist.")


def _success(audit_id: str, data: BaseModel) -> ToolResult:
    return ToolResult(
        ok=True, data=data.model_dump(mode="json"), error=None, audit_id=audit_id
    )


def _failure(audit_id: str, code: str, message: str) -> ToolResult:
    return ToolResult(
        ok=False,
        data=None,
        error=ToolErrorData(code=code, message=message),
        audit_id=audit_id,
    )


def _customer_data(customer: Customer) -> CustomerData:
    return CustomerData(
        id=customer.id, name=customer.name, email=customer.email, phone=customer.phone
    )


def _product_data(product: Product) -> ProductData:
    return ProductData(
        id=product.id,
        name=product.name,
        sku=product.sku,
        price=product.price,
        active=product.active,
    )


def _order_data(order: Order) -> OrderData:
    return OrderData(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        payment_status=order.payment_status,
        total_amount=order.total_amount,
        created_at=order.created_at,
        items=[
            OrderItemData(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            for item in order.items
        ],
    )


def _movement_data(movement: InventoryMovement) -> InventoryMovementData:
    return InventoryMovementData(
        id=movement.id,
        product_id=movement.product_id,
        movement_type=movement.movement_type,
        quantity=movement.quantity,
        reason=movement.reason,
        created_at=movement.created_at,
    )


def _transaction_data(transaction: Transaction) -> TransactionData:
    return TransactionData(
        id=transaction.id,
        order_id=transaction.order_id,
        type=transaction.type,
        status=transaction.status,
        amount=transaction.amount,
        description=transaction.description,
        created_at=transaction.created_at,
    )
