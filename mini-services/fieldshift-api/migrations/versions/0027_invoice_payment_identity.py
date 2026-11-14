"""Bind provider payment callbacks to invoices and transaction identities.

Revision ID: 0027_invoice_payment_identity
Revises: 0026_job_execution_ownership

Adds opaque provider invoice/transaction references to invoices and records the
invoice, provider transaction, and provider subscription identity on billing
events. Transaction-level uniqueness applies only to successfully processed
events; failed attempts remain auditable and retryable.
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_invoice_payment_identity"
down_revision = "0026_job_execution_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("provider_invoice_ref", sa.String(200), nullable=True))
    op.add_column("invoices", sa.Column("provider_transaction_ref", sa.String(200), nullable=True))
    op.create_index(
        "uq_invoice_provider_invoice_ref",
        "invoices",
        ["provider_ref", "provider_invoice_ref"],
        unique=True,
        postgresql_where=sa.text("provider_invoice_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_invoice_provider_transaction_ref", "invoices", ["provider_transaction_ref"]
    )

    op.add_column(
        "billing_events", sa.Column("provider_transaction_id", sa.String(200), nullable=True)
    )
    op.add_column(
        "billing_events", sa.Column("provider_subscription_ref", sa.String(200), nullable=True)
    )
    op.add_column(
        "billing_events",
        sa.Column(
            "invoice_id",
            sa.Uuid(),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_billing_event_provider_transaction",
        "billing_events",
        ["provider", "provider_transaction_id"],
        unique=True,
        postgresql_where=sa.text(
            "provider_transaction_id IS NOT NULL AND status IN ('processed','duplicate')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_billing_event_provider_transaction", table_name="billing_events")
    op.drop_column("billing_events", "invoice_id")
    op.drop_column("billing_events", "provider_subscription_ref")
    op.drop_column("billing_events", "provider_transaction_id")
    op.drop_index("ix_invoice_provider_transaction_ref", table_name="invoices")
    op.drop_index("uq_invoice_provider_invoice_ref", table_name="invoices")
    op.drop_column("invoices", "provider_transaction_ref")
    op.drop_column("invoices", "provider_invoice_ref")
