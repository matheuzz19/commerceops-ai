"""Order service that resolves tenant-scoped customer and product records."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from commerceops.domain.enums import OrderStatus, PaymentStatus
from commerceops.domain.invariants import DomainError, require_positive_quantity
from commerceops.domain.models import Order, OrderItem
from commerceops.repositories import CustomerRepository, OrderRepository, ProductRepository


@dataclass(frozen=True)
class OrderItemRequest:
    product_id: UUID
    quantity: int


class OrderService:
    def __init__(
        self,
        session: Session,
        order_repository: OrderRepository | None = None,
        customer_repository: CustomerRepository | None = None,
        product_repository: ProductRepository | None = None,
    ) -> None:
        self.session = session
        self.order_repository = order_repository or OrderRepository()
        self.customer_repository = customer_repository or CustomerRepository()
        self.product_repository = product_repository or ProductRepository()

    def create(
        self, tenant_id: UUID, customer_id: UUID, items: Sequence[OrderItemRequest]
    ) -> Order:
        if self.customer_repository.get(self.session, tenant_id, customer_id) is None:
            raise DomainError("CUSTOMER_NOT_FOUND", "Customer was not found.")
        if not items:
            raise DomainError("EMPTY_ORDER", "An order needs at least one item.")
        if len({item.product_id for item in items}) != len(items):
            raise DomainError("DUPLICATE_PRODUCT", "An order may contain each product once.")
        for item in items:
            require_positive_quantity(item.quantity)

        products = {
            product.id: product
            for product in self.product_repository.get_many(
                self.session, tenant_id, {item.product_id for item in items}
            )
        }
        if len(products) != len(items):
            raise DomainError("PRODUCT_NOT_FOUND", "One or more products were not found.")
        if any(not product.active for product in products.values()):
            raise DomainError("INACTIVE_PRODUCT", "Orders cannot include inactive products.")

        total = sum(
            (products[item.product_id].price * item.quantity for item in items), Decimal("0")
        )
        order = Order(tenant_id=tenant_id, customer_id=customer_id, total_amount=total)
        for item in items:
            product = products[item.product_id]
            order.items.append(
                OrderItem(
                    tenant_id=tenant_id,
                    product_id=product.id,
                    quantity=item.quantity,
                    unit_price=product.price,
                )
            )
        self.order_repository.add(self.session, order)
        self.session.flush()
        return order

    def list(
        self, tenant_id: UUID, customer_id: UUID | None = None, limit: int = 20
    ) -> Sequence[Order]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if (
            customer_id is not None
            and self.customer_repository.get(self.session, tenant_id, customer_id) is None
        ):
            raise DomainError("CUSTOMER_NOT_FOUND", "Customer was not found.")
        return self.order_repository.list_for_customer(self.session, tenant_id, customer_id, limit)

    def update(
        self,
        tenant_id: UUID,
        order_id: UUID,
        status: OrderStatus,
        payment_status: PaymentStatus | None = None,
    ) -> Order:
        order = self.order_repository.get(self.session, tenant_id, order_id)
        if order is None:
            raise DomainError("ORDER_NOT_FOUND", "Order was not found.")
        order.status = status
        if payment_status is not None:
            order.payment_status = payment_status
        self.session.flush()
        return order
