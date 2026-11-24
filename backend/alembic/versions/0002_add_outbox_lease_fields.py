"""add outbox lease fields and replace partial index

Revision ID: 0002_add_outbox_lease_fields
Revises: 95a77afedafe
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_add_outbox_lease_fields"
down_revision: str | None = "95a77afedafe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add dedicated columns for worker lease fencing and attempt counting
    op.add_column(
        "automation_events",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "automation_events",
        sa.Column(
            "lease_token",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "automation_events",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # 2. Drop existing single partial index using exact initial migration signature
    op.drop_index(
        "idx_outbox_unprocessed",
        table_name="automation_events",
        postgresql_where=sa.text("processing_status IN ('PENDING', 'PROCESSING')"),
    )

    # 3. Create Index A: Retry eligibility for PENDING and FAILED events
    op.create_index(
        "idx_outbox_retry_eligible",
        "automation_events",
        ["processing_status", "next_retry_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("processing_status IN ('PENDING', 'FAILED')"),
    )

    # 4. Create Index B: Lease recovery for in-flight PROCESSING events
    op.create_index(
        "idx_outbox_lease_recovery",
        "automation_events",
        ["lease_expires_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("processing_status = 'PROCESSING'"),
    )


def downgrade() -> None:
    # 1. Drop both purpose-built partial indexes
    op.drop_index(
        "idx_outbox_lease_recovery",
        table_name="automation_events",
        postgresql_where=sa.text("processing_status = 'PROCESSING'"),
    )
    op.drop_index(
        "idx_outbox_retry_eligible",
        table_name="automation_events",
        postgresql_where=sa.text("processing_status IN ('PENDING', 'FAILED')"),
    )

    # 2. Recreate exact original index from 95a77afedafe_initial_schema.py
    op.create_index(
        "idx_outbox_unprocessed",
        "automation_events",
        ["processing_status", "next_retry_at"],
        unique=False,
        postgresql_where=sa.text("processing_status IN ('PENDING', 'PROCESSING')"),
    )

    # 3. Drop columns in reverse order
    op.drop_column("automation_events", "lease_expires_at")
    op.drop_column("automation_events", "lease_token")
    op.drop_column("automation_events", "attempt_count")
