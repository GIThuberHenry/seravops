"""set_null_on_execution_log_step_id_and_cascade_executions

Revision ID: 8f2c3b4a5d6e
Revises: ca3078f12662
Create Date: 2026-08-31 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2c3b4a5d6e"
down_revision: str | None = "ca3078f12662"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_fk_name(table_name: str, column_name: str) -> str | None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for fk in insp.get_foreign_keys(table_name):
        if column_name in fk.get("constrained_columns", []):
            return fk.get("name")
    return None


def upgrade() -> None:
    # 1. Update execution_logs.step_id -> recipe_steps.id with ON DELETE SET NULL
    step_fk = _get_fk_name("execution_logs", "step_id")
    if step_fk:
        op.drop_constraint(step_fk, "execution_logs", type_="foreignkey")
    op.create_foreign_key(
        step_fk or "execution_logs_step_id_fkey",
        "execution_logs",
        "recipe_steps",
        ["step_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. Update recipe_executions.recipe_id -> recipes.id with ON DELETE CASCADE (ensuring MySQL is covered)
    recipe_fk = _get_fk_name("recipe_executions", "recipe_id")
    if recipe_fk:
        op.drop_constraint(recipe_fk, "recipe_executions", type_="foreignkey")
    op.create_foreign_key(
        recipe_fk or "recipe_executions_recipe_id_fkey",
        "recipe_executions",
        "recipes",
        ["recipe_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    step_fk = _get_fk_name("execution_logs", "step_id")
    if step_fk:
        op.drop_constraint(step_fk, "execution_logs", type_="foreignkey")
    op.create_foreign_key(
        step_fk or "execution_logs_step_id_fkey",
        "execution_logs",
        "recipe_steps",
        ["step_id"],
        ["id"],
    )

    recipe_fk = _get_fk_name("recipe_executions", "recipe_id")
    if recipe_fk:
        op.drop_constraint(recipe_fk, "recipe_executions", type_="foreignkey")
    op.create_foreign_key(
        recipe_fk or "recipe_executions_recipe_id_fkey",
        "recipe_executions",
        "recipes",
        ["recipe_id"],
        ["id"],
    )
