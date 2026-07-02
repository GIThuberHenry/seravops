"""Initial schema and development seed data.

Revision ID: 20260702_0001
Revises:
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pwdlib import PasswordHash

revision: str = "20260702_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_role = sa.Enum("ADMIN", "DEVELOPER", name="userrole", native_enum=False)
    step_kind = sa.Enum("COMMAND", "GIT_PULL", "NGINX", name="stepkind", native_enum=False)
    execution_status = sa.Enum(
        "PENDING", "RUNNING", "SUCCESS", "FAILED", name="executionstatus", native_enum=False
    )
    log_stream = sa.Enum("STDOUT", "STDERR", "SYSTEM", name="logstream", native_enum=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("framework", sa.String(50), nullable=False),
        sa.Column("target_server", sa.String(20), nullable=False),
        sa.Column("app_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_services_slug", "services", ["slug"], unique=True)
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "recipe_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipes.id", ondelete="CASCADE")),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", step_kind, nullable=False),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
    )
    op.create_table(
        "recipe_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipe_id", sa.Integer(), sa.ForeignKey("recipes.id"), nullable=False),
        sa.Column("triggered_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", execution_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "execution_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("recipe_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("recipe_steps.id"), nullable=True),
        sa.Column("stream", log_stream, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_logs_execution_id", "execution_logs", ["execution_id"])
    op.create_index("ix_execution_logs_created_at", "execution_logs", ["created_at"])

    now = sa.func.now()
    hasher = PasswordHash.recommended()
    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("username", sa.String()),
        sa.column("password_hash", sa.String()),
        sa.column("role", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        users,
        [
            {
                "id": 1,
                "username": "admin",
                "password_hash": hasher.hash("admin123"),
                "role": "ADMIN",
                "created_at": now,
            },
            {
                "id": 2,
                "username": "developer",
                "password_hash": hasher.hash("developer123"),
                "role": "DEVELOPER",
                "created_at": now,
            },
        ],
    )
    services = sa.table(
        "services",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("framework", sa.String()),
        sa.column("target_server", sa.String()),
        sa.column("app_path", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        services,
        [
            {
                "id": 1,
                "name": "Seravops Demo",
                "slug": "seravops-demo",
                "framework": "FastAPI",
                "target_server": "server_1",
                "app_path": "/tmp/seravops-demo",
                "created_at": now,
            }
        ],
    )
    recipes = sa.table(
        "recipes",
        sa.column("id", sa.Integer()),
        sa.column("service_id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        recipes,
        [
            {
                "id": 1,
                "service_id": 1,
                "name": "Update",
                "description": "Pull the latest revision and restart the demo service.",
                "created_at": now,
            }
        ],
    )
    steps = sa.table(
        "recipe_steps",
        sa.column("id", sa.Integer()),
        sa.column("recipe_id", sa.Integer()),
        sa.column("position", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("command", sa.Text()),
        sa.column("config", sa.JSON()),
    )
    op.bulk_insert(
        steps,
        [
            {
                "id": 1,
                "recipe_id": 1,
                "position": 1,
                "name": "Pull latest code",
                "kind": "GIT_PULL",
                "command": None,
                "config": {},
            },
            {
                "id": 2,
                "recipe_id": 1,
                "position": 2,
                "name": "Restart service",
                "kind": "COMMAND",
                "command": "echo 'seravops-demo restarted successfully'",
                "config": {},
            },
        ],
    )
    for table_name, value in {
        "users": 2,
        "services": 1,
        "recipes": 1,
        "recipe_steps": 2,
    }.items():
        op.execute(sa.text(f"SELECT setval('{table_name}_id_seq', {value}, true)"))


def downgrade() -> None:
    op.drop_index("ix_execution_logs_created_at", table_name="execution_logs")
    op.drop_index("ix_execution_logs_execution_id", table_name="execution_logs")
    op.drop_table("execution_logs")
    op.drop_table("recipe_executions")
    op.drop_table("recipe_steps")
    op.drop_table("recipes")
    op.drop_index("ix_services_slug", table_name="services")
    op.drop_table("services")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
