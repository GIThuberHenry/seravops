"""cascade_delete_recipe_executions

Revision ID: 17fb071bfece
Revises: 20260702_0001
Create Date: 2026-07-04 16:41:47.801207
"""

from collections.abc import Sequence

from alembic import op

revision: str = "17fb071bfece"
down_revision: str | None = "20260702_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the existing FK on recipe_executions.recipe_id (no ondelete set)
    # and recreate it with ON DELETE CASCADE so that deleting a recipe
    # automatically removes all its executions (and their logs via their own CASCADE).
    op.drop_constraint(
        "recipe_executions_recipe_id_fkey",
        "recipe_executions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "recipe_executions_recipe_id_fkey",
        "recipe_executions",
        "recipes",
        ["recipe_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "recipe_executions_recipe_id_fkey",
        "recipe_executions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "recipe_executions_recipe_id_fkey",
        "recipe_executions",
        "recipes",
        ["recipe_id"],
        ["id"],
    )
