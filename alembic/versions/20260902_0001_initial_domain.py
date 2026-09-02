"""Initial CommerceOps domain schema.

Revision ID: 20260902_0001
Revises:
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260902_0001"
down_revision = None
branch_labels = None
depends_on = None


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "users",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "role",
            sa.Enum("ADMIN", "OPERATOR", "VIEWER", name="userrole", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_table(
        "customers",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320)),
        sa.Column("phone", sa.String(length=50)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.create_index("ix_customers_name", "customers", ["name"])
    op.create_table(
        "products",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_index("ix_products_name", "products", ["name"])
    op.create_table(
        "orders",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("customer_id", _uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "CONFIRMED",
                "CANCELLED",
                "FULFILLED",
                name="orderstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "payment_status",
            sa.Enum(
                "UNPAID", "PAID", "REFUNDED", name="paymentstatus", native_enum=False, length=20
            ),
            nullable=False,
        ),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_table(
        "order_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("order_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_items_tenant_id", "order_items", ["tenant_id"])
    op.create_table(
        "inventory_movements",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column(
            "movement_type",
            sa.Enum(
                "IN",
                "OUT",
                "ADJUSTMENT",
                name="inventorymovementtype",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_movements_tenant_id", "inventory_movements", ["tenant_id"])
    op.create_table(
        "transactions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("order_id", _uuid()),
        sa.Column(
            "type",
            sa.Enum("REVENUE", "EXPENSE", name="transactiontype", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "POSTED",
                "CANCELLED",
                name="transactionstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_tenant_id", "transactions", ["tenant_id"])


def downgrade() -> None:
    for table in (
        "transactions",
        "inventory_movements",
        "order_items",
        "orders",
        "products",
        "customers",
        "users",
        "tenants",
    ):
        op.drop_table(table)
