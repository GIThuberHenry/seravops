"""add_allowed_ips_to_users

Revision ID: ca3078f12662
Revises: 17fb071bfece
Create Date: 2026-07-13 04:05:43
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ca3078f12662"
down_revision: str | None = "17fb071bfece"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("allowed_ips", sa.String(2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "allowed_ips")
