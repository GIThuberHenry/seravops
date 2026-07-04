# AGENT.md — Seravops AI Agent Context

This file provides context for AI coding assistants (Copilot, Gemini, Claude, etc.) working on the Seravops codebase. Read this before making changes.

---

## What is Seravops?

Seravops is a **deployment recipe orchestration platform** — an internal developer platform (IDP) in the spirit of an Open Service Broker. It lets:

- **Admins** register services (deployed apps on remote servers), define recipes (ordered deployment steps), and configure server credentials
- **Developers** trigger recipes on demand through a web UI or JSON API, with live streaming logs

It is **not** a generic job scheduler or CI/CD system. It is an opinionated, single-binary FastAPI application backed by PostgreSQL that does exactly three things well:
1. Run shell commands over SSH (or locally)
2. `git pull` a repo on a remote server
3. Safely validate and apply an nginx reverse proxy config

---

## Architecture at a Glance

```
Browser / API Client
        │
        ▼
   FastAPI (uvicorn)
        │
   ┌────┴────────────────────────────────────┐
   │  Routers (thin HTTP layer)              │
   │  auth / services / recipes / executions │
   └────┬────────────────────────────────────┘
        │  calls
   ┌────▼────────────────────────────────────┐
   │  Services (business logic)              │
   │  recipe_service ← ssh_service           │
   │                ← git_service            │
   │                ← nginx_service          │
   │  auth_service, service_service          │
   └────┬────────────────────────────────────┘
        │  SQLAlchemy 2.0 async
   ┌────▼───────┐
   │ PostgreSQL │
   └────────────┘
```

**Key design rules:**
- Routers only validate input, enforce role deps, call one service function, and shape the response
- All business logic lives in `app/services/`
- There is no repository pattern — services call `AsyncSession` directly
- No separate frontend build — Jinja2 templates + HTMX + vanilla CSS

---

## Data Model

```
User
  └─ executions: RecipeExecution[]

Service
  └─ recipes: Recipe[]
       └─ steps: RecipeStep[]
       └─ executions: RecipeExecution[]
            └─ logs: ExecutionLog[]
```

### Key Tables

| Table              | Purpose                                                      |
|--------------------|--------------------------------------------------------------|
| `users`            | Auth principals with `admin` or `developer` role             |
| `services`         | Registered deployable applications                           |
| `recipes`          | Named collections of steps, scoped to a service              |
| `recipe_steps`     | Ordered steps: `kind` ∈ {`command`, `git_pull`, `nginx`}     |
| `recipe_executions`| A single run of a recipe; tracks status + timestamps         |
| `execution_logs`   | Per-line stdout/stderr/system messages streamed during a run |

### Enums (`app/models/enums.py`)

| Enum              | Values                                         |
|-------------------|------------------------------------------------|
| `UserRole`        | `admin`, `developer`                           |
| `StepKind`        | `command`, `git_pull`, `nginx`                 |
| `ExecutionStatus` | `pending`, `running`, `success`, `failed`      |
| `LogStream`       | `stdout`, `stderr`, `system`                   |

---

## Execution Flow

```
POST /executions/run
  │
  ├─ create RecipeExecution (status=pending) in DB
  ├─ schedule BackgroundTask: run_recipe_execution(execution_id)
  └─ redirect to /executions/{id}

run_recipe_execution()
  │
  ├─ set status=running, started_at=now
  ├─ for each RecipeStep (ordered by position):
  │    ├─ append SYSTEM log: "Starting step N: <name>"
  │    ├─ _execute_step() → dispatches to ssh/git/nginx service
  │    │    stdout/stderr lines → _append_log() per line (own DB session)
  │    ├─ append SYSTEM log: "Step finished with exit code N"
  │    └─ if exit_code != 0: set status=failed, return early
  └─ set status=success, finished_at=now

Browser
  └─ HTMX polls GET /executions/{id} every 2s
       └─ returns _status.html fragment (HX-Request header) or full page
```

---

## SSH / Local Execution Logic

File: [`app/services/ssh_service.py`](app/services/ssh_service.py)

- Target `localhost` / `127.0.0.1` / `::1` → `asyncio.create_subprocess_shell` (local)
- Any other host → `asyncssh.connect()` + `connection.create_process()` (remote SSH)
- Both paths stream stdout and stderr concurrently via `asyncio.gather`
- Output is delivered line-by-line to an `OutputHandler` callback (which writes `ExecutionLog` rows)

---

## Nginx Safety Protocol

File: [`app/services/nginx_service.py`](app/services/nginx_service.py)

1. Render `templates/nginx/reverse_proxy.conf.j2` with `subdomain`, `upstream_port`, `service_name`
2. Write rendered config to `/tmp/seravops-<name>.conf` (candidate)
3. Write a minimal wrapper nginx config that includes the candidate
4. Run `nginx -t -c /tmp/seravops-<name>-nginx.conf`
5. If validation fails → stream error, return non-zero, **do not touch `/etc/nginx/conf.d/`**
6. If validation passes → `install -m 0644 <candidate> /etc/nginx/conf.d/<name>.conf && nginx -s reload`

---

## Authentication & Authorization

File: [`app/core/security.py`](app/core/security.py)

- JWT HS256 tokens issued via `POST /auth/token` (API) or `POST /login` (form, sets HttpOnly cookie)
- Token carries `sub` (user ID) and `role`
- `require_auth` dependency: checks Bearer header first, then `access_token` cookie
- `require_admin` dependency: wraps `require_auth`, raises 403 if role ≠ `admin`
- 401 on HTML pages → auto-redirect to `/login`

---

## Environment Variables

| Variable                     | Default                                              | Notes                                  |
|------------------------------|------------------------------------------------------|----------------------------------------|
| `DATABASE_URL`               | `postgresql+asyncpg://seravops:seravops@postgres/seravops` | Must be asyncpg scheme         |
| `JWT_SECRET`                 | `change-me-in-production`                            | Must be changed before production      |
| `ACCESS_TOKEN_EXPIRE_MINUTES`| `480`                                                | 8 hours                                |
| `DEBUG`                      | `false`                                              | Enables cookie `secure=False`          |
| `SERVER_1_HOST`              | `localhost`                                          | `localhost` triggers local subprocess  |
| `SERVER_1_USER`              | `root`                                               |                                        |
| `SERVER_1_PORT`              | `22`                                                 |                                        |
| `SERVER_1_KEY_PATH`          | _(empty)_                                            | Path to mounted SSH private key        |
| `SERVER_2_*`                 | —                                                    | Same pattern as SERVER_1               |

---

## API Routes Summary

### HTML UI Routes

| Method | Path                              | Auth    | Description                         |
|--------|-----------------------------------|---------|-------------------------------------|
| GET    | `/login`                          | —       | Login page                          |
| POST   | `/login`                          | —       | Form login → set cookie             |
| POST   | `/logout`                         | —       | Clear cookie                        |
| GET    | `/services`                       | Any     | Service list                        |
| GET    | `/services/new`                   | Admin   | Register service form               |
| POST   | `/services/new`                   | Admin   | Submit service registration         |
| GET    | `/services/{id}/recipes`          | Any     | Recipe list for service             |
| GET    | `/services/{id}/recipes/new`      | Admin   | New recipe form + step builder      |
| POST   | `/services/{id}/recipes/new`      | Admin   | Submit recipe creation              |
| GET    | `/recipes/{id}`                   | Any     | Recipe detail + execution history   |
| POST   | `/executions/run`                 | Any     | Trigger execution (form)            |
| GET    | `/executions/{id}`                | Any     | Execution detail (HTML/HTMX)        |

### JSON API Routes

| Method | Path                        | Auth    | Description                    |
|--------|-----------------------------|---------|--------------------------------|
| POST   | `/auth/token`               | —       | Issue JWT (OAuth2 form)        |
| GET    | `/api/services`             | Any     | Service list (JSON)            |
| POST   | `/services`                 | Admin   | Create service (JSON)          |
| GET    | `/services/{id}`            | Any     | Service detail (JSON)          |
| GET    | `/api/recipes/{id}`         | Any     | Recipe detail (JSON)           |
| POST   | `/recipes`                  | Admin   | Create recipe (JSON)           |
| GET    | `/api/executions/{id}`      | Any     | Execution detail (JSON)        |
| GET    | `/health`                   | —       | Health check                   |
| GET    | `/docs`                     | —       | Swagger UI                     |

---

## Coding Conventions

### General
- Python 3.12+; use `from __future__ import annotations` only if needed for forward refs
- All async — use `async def` and `await` everywhere; no blocking I/O
- Pydantic v2 for all schemas; use `model_validate()` for ORM → schema
- SQLAlchemy 2.0 style (`Mapped`, `mapped_column`, `select()`, `scalars()`)
- Structured logging via `structlog`; use `logger.info("event_name", key=value)` — no f-string messages
- Line length: 100 characters (Black + Ruff enforced)

### Adding a Service Function
```python
# In app/services/my_service.py
async def do_thing(db: AsyncSession, ...) -> MyModel:
    ...
```

### Adding a Form-Based HTML Route

For routes that accept HTML form submissions (like the service/recipe creation forms):

```python
@router.post("/things/new", response_class=HTMLResponse)
async def thing_new_submit(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    name: Annotated[str, Form()] = "",
    # ...other fields
) -> HTMLResponse:
    try:
        data = ThingCreate(name=name, ...)
        thing = await thing_service.create_thing(db, data)
        return RedirectResponse(f"/things/{thing.id}", status_code=303)
    except ValidationError as exc:
        error = "; ".join(e["msg"] for e in exc.errors())
        return templates.TemplateResponse(
            request, "things/new.html",
            {"current_user": user, "error": error, "form": {"name": name}},
            status_code=422,
        )
```

For dynamic multi-item form data (like recipe steps), parse `request.form()` directly:

```python
raw = await request.form()
# keys like steps[0][name], steps[0][kind], steps[1][name] ...
for key, val in raw.multi_items():
    if key.startswith("steps["):
        idx = int(key[6:key.index("]")])
        field = key[key.index("]")+2:-1]
        steps_by_index.setdefault(idx, {})[field] = val
```

### Adding a Router Endpoint (JSON API)
```python
# In app/routers/my_router.py
@router.post("/things", response_model=ThingResponse, status_code=201)
async def create_thing(
    data: ThingCreate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThingResponse:
    result = await my_service.create_thing(db, data)
    return ThingResponse.model_validate(result)
```

### Adding a New Step Kind
1. Add value to `StepKind` in `app/models/enums.py`
2. Generate Alembic migration: `make migrate` (after `alembic revision --autogenerate -m "add X step kind"`)
3. Implement logic in `app/services/` returning `CommandResult`
4. Add dispatch branch in `_execute_step()` in `app/services/recipe_service.py`
5. Add `model_validator` logic in `app/schemas/recipe.py` for any required `config` keys
6. Write tests in `tests/test_recipe_service.py` using the mocked SSH pattern

---

## Testing

Tests live in `tests/` and use:
- `pytest-asyncio` with `asyncio_mode = "auto"`
- In-memory async SQLite via `aiosqlite` (not PostgreSQL)
- Mocked SSH execution — no real SSH connections in tests

```bash
make test          # run all tests
make lint          # ruff + black check
```

Key test files:
- `tests/conftest.py` — async SQLite DB fixture and session factory
- `tests/test_recipe_service.py` — recipe CRUD and execution flow
- `tests/test_nginx_service.py` — nginx render and validation logic
- `tests/test_auth_service.py` — password hashing and token issuance

---

## Common Gotchas

| Situation | Watch Out For |
|---|---|
| Adding a model field | Always generate a new Alembic migration |
| Nginx step config | `config` dict must have `subdomain`, `upstream_port`, `service_name` keys |
| Local vs remote SSH | `localhost`/`127.0.0.1`/`::1` → local subprocess, no key needed |
| BackgroundTask limits | App restart kills in-flight executions; consider a durable queue for production |
| `StepKind.NGINX` config | The `config` field is a raw `dict` in the DB (JSON column); validate in schemas |
| Two servers only | Currently hardcoded to `server_1` / `server_2`; adding more requires config changes |
| Cookie security | `secure=False` only when `DEBUG=true`; always `True` in production |
| `/services/new` route order | Must be registered **before** `/services/{service_id}` or FastAPI matches "new" as an int ID |
| Form data for dynamic steps | Use `await request.form()` + manual `steps[N][field]` parsing; `Form()` params only work for fixed fields |
| `list_executions` in recipe detail | Eager-loads `triggered_by` user; don't forget the `selectinload` or you'll get lazy-load errors in async |
| Execution history stays `running` | App restart during execution leaves status stuck; manually update or re-trigger |

---

## Future Extension Points

- **More servers**: `config.py` has a `server()` method keyed on `"server_1"` / `"server_2"`; extending to N servers needs an enum or a `servers` table
- **More step kinds**: Follow the 5-step pattern in `AGENT.md` → Adding a New Step Kind (don't forget to add the kind toggle in `recipes/new.html`)
- **Durable execution queue**: Replace `BackgroundTasks` with ARQ, Celery, or a worker polling a `job_queue` table
- **Webhook triggers**: Add a signed `POST /webhooks/{service_slug}/trigger` route that maps to a default recipe
- **Audit log**: Add a `UserAction` table written by admin-only mutations
- **Multi-tenant**: Add an `Organization` model and scope services/recipes per org
- **Recipe editing**: Add `PUT /recipes/{id}` (JSON) and `GET/POST /recipes/{id}/edit` (HTML form) routes
- **Service deletion**: Add `DELETE /services/{id}` with cascade behaviour and a confirmation UI
- **User management UI**: Admin page to create/reset passwords for other users
