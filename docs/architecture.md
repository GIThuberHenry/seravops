# Architecture — Seravops

This document describes the system design, data flow, and component interactions in Seravops.

---

## Overview

Seravops is a **single-process FastAPI application** with a PostgreSQL database. There are no background workers, message queues, or external services beyond the database. Complexity is deliberately minimized — the app runs as one Docker container next to one Postgres container.

```
┌──────────────────────────────────────────────────────────────┐
│                     Docker Compose Stack                     │
│                                                              │
│  ┌─────────────────────────────┐   ┌──────────────────────┐ │
│  │   seravops app container    │   │  postgres container   │ │
│  │                             │   │                       │ │
│  │  FastAPI + uvicorn :7372    │──▶│  PostgreSQL :5432     │ │
│  │                             │   │                       │ │
│  │  ┌──────────────────────┐   │   └──────────────────────┘ │
│  │  │  BackgroundTasks     │   │                            │
│  │  │  (in-process runner) │   │  ┌──────────────────────┐  │
│  │  └──────────────────────┘   │  │  Remote Server(s)     │  │
│  │                             │──▶│  SSH :22              │  │
│  └─────────────────────────────┘  └──────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## Request Path

### Browser / HTMX

```
Browser
  └─ GET /services                 → Jinja2 HTML page
  └─ POST /executions/run (form)   → redirect to /executions/{id}
  └─ GET /executions/{id}          → full HTML page
  └─ GET /executions/{id}          → _status.html fragment (HX-Request: true, every 2s)
```

### API Client (CI/CD, scripts)

```
API Client
  └─ POST /auth/token              → Bearer JWT
  └─ POST /recipes (Bearer)        → create recipe
  └─ POST /executions/run (Bearer) → trigger execution
  └─ GET /api/executions/{id}      → poll for status/logs (JSON)
```

---

## Layer Responsibilities

| Layer | Location | Responsibility |
|---|---|---|
| **Router** | `app/routers/` | Parse request, enforce auth dependency, call one service function, return response |
| **Service** | `app/services/` | All business logic, DB writes, SSH calls, orchestration |
| **Model** | `app/models/` | SQLAlchemy ORM table definitions, enums |
| **Schema** | `app/schemas/` | Pydantic v2 request/response validation |
| **Core** | `app/core/` | Settings, JWT, security dependencies, logging |

**Design rule:** routers never touch `AsyncSession` for business logic — they only pass `db` into service calls.

---

## Execution Engine

Executions are driven by FastAPI's `BackgroundTasks`. When `POST /executions/run` is called:

1. A `RecipeExecution` row is inserted with `status=pending`
2. The response immediately redirects to `/executions/{id}` (303)
3. A coroutine is registered with `BackgroundTasks` — it runs after the HTTP response is sent
4. The coroutine calls `run_recipe_execution(execution_id)`

### Why BackgroundTasks (and its limits)

`BackgroundTasks` is simple, zero-dependency, and in-process. It is appropriate for:
- Short-lived recipes (a few seconds to a minute)
- Single-instance deployments

It is **not** appropriate for:
- Long-running recipes (risk of HTTP timeout or app restart interruption)
- Multi-replica deployments (tasks are process-local)
- High-throughput scenarios (recipes block the asyncio event loop if they wait on SSH)

**Upgrade path:** Replace the `background_tasks.add_task(...)` call with a message to ARQ, Celery, or a `job_queue` DB table polled by a separate worker process. The `run_recipe_execution()` function itself is already self-contained — it only needs an `execution_id` and an `async_session_factory`.

---

## Log Streaming

Each stdout/stderr line from SSH or a local subprocess is committed to `execution_logs` immediately in a short-lived, dedicated `AsyncSession`. This approach:
- Avoids holding a long-lived session open during execution
- Makes partial logs visible if a recipe fails mid-way
- Enables HTMX polling to show incremental progress

The browser polls `GET /executions/{id}` every 2 seconds. The route returns:
- A full HTML page for direct navigation
- The `executions/_status.html` HTMX fragment when the `HX-Request: true` header is present

Polling stops when the HTMX fragment detects `status=success` or `status=failed`.

---

## Database Schema

```
users
  id, username, hashed_password, role (admin|developer), created_at

services
  id, name, slug, framework, target_server (server_1|server_2), app_path, created_at

recipes
  id, service_id (FK→services), name, description, created_at

recipe_steps
  id, recipe_id (FK→recipes), position, name, kind, command, config (JSON)

recipe_executions
  id, recipe_id (FK→recipes), triggered_by_id (FK→users),
  status (pending|running|success|failed),
  started_at, finished_at, created_at

execution_logs
  id, execution_id (FK→recipe_executions, indexed),
  step_id (FK→recipe_steps, nullable),
  stream (stdout|stderr|system), message, exit_code (nullable),
  created_at (indexed)
```

---

## SSH Execution

`ssh_service.execute(command, target, on_output)` routes to:

```python
if target.host in {"localhost", "127.0.0.1", "::1"}:
    # asyncio.create_subprocess_shell
else:
    # asyncssh.connect() + connection.create_process()
```

Both paths:
- Stream stdout and stderr concurrently with `asyncio.gather`
- Call `on_output(stream, line)` for every line — this callback writes to the DB
- Return `CommandResult(exit_code=int)`

Authentication: key-based SSH only. `key_path` is a path to a file mounted into the container.

---

## Security Model

- **JWT HS256** — secret in `JWT_SECRET` env var; tokens expire in `ACCESS_TOKEN_EXPIRE_MINUTES`
- **Cookie auth** — HttpOnly `access_token` cookie for browser sessions
- **Bearer auth** — `Authorization: Bearer <token>` for API clients
- **Role enforcement** — `require_admin` FastAPI dependency wraps `require_auth`; 403 if not admin
- **Automatic redirect** — 401 responses to HTML requests redirect to `/login`
- **Password hashing** — `pwdlib[argon2]`; bcrypt fallback available

---

## Component Interaction Diagram

```
┌─────────┐  POST /executions/run   ┌──────────────┐
│ Browser │ ───────────────────────▶│  executions  │
│  / API  │                         │    router    │
│  client │◀─ 303 redirect ─────────│              │
└────┬────┘                         └──────┬───────┘
     │                                     │ create_execution()
     │ GET /executions/{id}                │ add_task(run_recipe_execution)
     │ every 2s (HTMX)             ┌───────▼──────────────────────────┐
     │                             │         recipe_service           │
     │                             │  run_recipe_execution()          │
     │                             │    → _set_execution_status()     │
     │                             │    → for step in steps:          │
     │                             │        _execute_step()           │
     │                             │          ├─ ssh_service.execute()│
     │                             │          ├─ git_service.pull()   │
     │                             │          └─ nginx_service.v&a()  │
     │                             │        → _append_log() per line  │
     │                             └──────────────────────────────────┘
     │                                              │
     │ ◀─ execution + logs HTML ─────────────────── │
     │    (fragment or full page)            PostgreSQL
```
