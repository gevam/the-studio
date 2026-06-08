"""Add slice rework accounting columns (§2.3 unified rework budget).

Persists the per-slice rework usage and whether the slice was force-accepted on
cap exhaustion — the source the §7.5 Design Health dashboards read to tell genuine
convergence from accept-on-cap.

Revision ID: 002
Revises: 001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slices",
        sa.Column("rework_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "slices",
        sa.Column(
            "accepted_under_cap", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("slices", "accepted_under_cap")
    op.drop_column("slices", "rework_used")
