"""add_google_oauth_to_users

Revision ID: 9a1b2c3d4e5f
Revises: 8f2c3b4a5d6e
Create Date: 2026-09-10 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a1b2c3d4e5f"
down_revision: str | None = "8f2c3b4a5d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("password_hash", existing_type=sa.String(255), nullable=True)
        batch_op.add_column(sa.Column("email", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("google_id", sa.String(255), nullable=True))
        batch_op.create_index("ix_users_email", ["email"], unique=True)
        batch_op.create_index("ix_users_google_id", ["google_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_google_id")
        batch_op.drop_index("ix_users_email")
        batch_op.drop_column("google_id")
        batch_op.drop_column("email")
        batch_op.alter_column("password_hash", existing_type=sa.String(255), nullable=False)
