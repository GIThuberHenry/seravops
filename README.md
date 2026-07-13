# Seravops

**Seravops** is a self-hosted deployment orchestration platform — an Open Service Broker-style API and web UI that lets **admins define recipes** (ordered deployment steps) and **developers trigger them** against registered services running on one or more remote servers.

Think of it as your internal platform engineering tool: admins codify _how_ to deploy, update, git pull, or reconfigure nginx for any service, and developers can execute those recipes on demand, with live streaming logs.

```
Admin   → defines services, registers servers, authors recipes
Developer → picks a service, selects a recipe, triggers an execution, watches live logs
```

---

## Features

- **Recipe-based deployments** — ordered steps combining shell commands, `git pull`, and safe nginx config updates
- **Multi-server targeting** — each service is pinned to `server_1` or `server_2`; credentials are injected via env vars, never stored in the database
- **SSH + local execution** — uses `asyncssh` for remote targets; `localhost`/`127.0.0.1` falls back to a local subprocess (useful for in-container tasks)
- **Safe nginx management** — renders, validates (`nginx -t`), and only applies config if validation passes; a bad config never replaces a good one
- **Live log streaming** — execution stdout/stderr is committed row-by-row to PostgreSQL; the browser polls with HTMX every 2 seconds for a live-terminal feel
- **Role-based access control** — JWT auth with `admin` and `developer` roles; only admins can manage users, create services, or build recipes
- **Full admin web UI** — create, edit, and delete services, recipes, and users directly in the browser with a dynamic step builder; no API calls required
- **Execution history** — recipe detail pages show the last 20 executions with status, triggering user, and timestamp
- **IP whitelist field** — each user has an `allowed_ips` field (comma-separated) ready for middleware enforcement
- **Dual interface** — full HTML/HTMX UI served by Jinja2 templates _and_ a JSON API (documented at `/docs`) for CI/CD or scripting

---

## Quick Start

Only Docker and Docker Compose are required. The web application runs on port `7372` (`SERA` on a telephone keypad).

```bash
cp .env.example .env
make up
make migrate
```

Open <http://localhost:7372>. The initial migration seeds:

| Role      | Username    | Password       |
|-----------|-------------|----------------|
| Admin     | `admin`     | `admin123`     |
| Developer | `developer` | `developer123` |

It also creates a **Seravops Demo** service and an **Update** recipe. The entrypoint creates a disposable Git origin under `/tmp` so the recipe performs a real `git pull --ff-only` — meaning the **login → service → recipe → run → live logs** flow is testable immediately out of the box.

> **Security**: Change the seeded passwords and `JWT_SECRET` before exposing the app outside a local environment.

---

## Common Commands

```bash
make up       # build and start app + PostgreSQL
make migrate  # run Alembic migrations
make test     # run pytest inside the app container
make lint     # run Ruff and Black checks
make logs     # follow application logs
make down     # stop containers
```

Interactive API documentation is at <http://localhost:7372/docs>.

API clients can obtain a Bearer token from `POST /auth/token`, then use it as:
```
Authorization: Bearer <token>
```

---

## Concepts

### Services

A **Service** represents a deployed application on a target server. It stores:
- `name` / `slug` — display name and URL-safe identifier
- `framework` — informational label (e.g. `fastapi`, `django`, `node`)
- `target_server` — which configured server (`server_1` or `server_2`) runs this service
- `app_path` — absolute path on the target server (used as the working directory for commands)

Admins register services via the **web UI** (`/services/new`) or the JSON API (`POST /services`).

### Recipes

A **Recipe** is an ordered collection of **steps** associated with a specific service. Each step has a `kind`:

| Kind       | What it does                                                             |
|------------|--------------------------------------------------------------------------|
| `command`  | Runs an arbitrary shell command in the service's `app_path`              |
| `git_pull` | Runs `git pull --ff-only` in `app_path`                                  |
| `nginx`    | Renders, validates, and hot-reloads an nginx reverse proxy config block  |

Admins create recipes via the **web UI** (`/services/{id}/recipes/new`) with a dynamic step builder, or via the JSON API (`POST /recipes`). Developers can view recipes, see execution history, and trigger executions.

### Executions

When a recipe is triggered, an **Execution** record is created. It progresses through:
`pending` → `running` → `success` | `failed`

Every line of stdout/stderr from each step is saved as an `ExecutionLog` row immediately, allowing the browser to stream progress in near-real-time via HTMX polling.

---

## Project Layout

```text
app/
├── core/           # Settings, JWT/RBAC security, structured logging, DI dependencies
├── models/         # SQLAlchemy 2.0 async ORM models (Service, Recipe, RecipeStep, Execution, ExecutionLog, User)
├── routers/        # Thin FastAPI request handlers (HTML + /api/... JSON routes)
├── schemas/        # Pydantic v2 request/response models
├── services/       # Business logic: recipe orchestration, SSH, Git, nginx, auth
│   ├── recipe_service.py   # Orchestrates execution flow; dispatches to step executors
│   ├── ssh_service.py      # asyncssh remote + asyncio local subprocess execution
│   ├── git_service.py      # git pull / git clone wrappers
│   ├── nginx_service.py    # Render → validate → apply nginx config safely
│   ├── auth_service.py     # Password verification and token issuance
│   ├── service_service.py  # Service CRUD (create, update, delete)
│   └── user_service.py     # User CRUD (create, update, delete, password hashing)
├── static/         # Hand-written CSS stylesheet
├── templates/      # Jinja2 HTML pages, HTMX fragments, nginx Jinja2 template
├── db.py           # Async SQLAlchemy engine and session factory
└── main.py         # FastAPI application factory
migrations/         # Alembic environment and version scripts
tests/              # Service-layer tests (async SQLite + mocked SSH)
docs/               # Extended documentation
```

---

## Web UI Pages

| Page | Path | Who |
|---|---|---|
| Service list | `/services` | All |
| **Register service** | `/services/new` | Admin |
| **Edit / delete service** | `/services/{id}/edit` | Admin |
| Recipe list for service | `/services/{id}/recipes` | All |
| **New recipe builder** | `/services/{id}/recipes/new` | Admin |
| **Edit / delete recipe** | `/recipes/{id}/edit` | Admin |
| Recipe detail + execution history | `/recipes/{id}` | All |
| Live execution log | `/executions/{id}` | All |
| **User list** | `/users` | Admin |
| **New user form** | `/users/new` | Admin |
| **Edit / delete user** | `/users/{id}/edit` | Admin |

## JSON API Overview

| Method | Path                           | Auth     | Description                          |
|--------|--------------------------------|----------|--------------------------------------|
| POST   | `/auth/token`                  | —        | Issue a JWT Bearer token             |
| GET    | `/api/services`                | Any      | List all registered services         |
| POST   | `/services`                    | Admin    | Register a new service               |
| GET    | `/api/recipes/{id}`            | Any      | Get a recipe with its steps          |
| POST   | `/recipes`                     | Admin    | Create a recipe with ordered steps   |
| POST   | `/executions/run`              | Any      | Trigger a recipe execution           |
| GET    | `/api/executions/{id}`         | Any      | Get execution status and logs        |
| GET    | `/health`                      | —        | Health check                         |

Full interactive docs: <http://localhost:7372/docs>

---

## Creating a Recipe (API)

Authenticate as admin and `POST /recipes`:

```json
{
  "service_id": 1,
  "name": "Deploy workers",
  "description": "Pull latest code and restart workers",
  "steps": [
    { "position": 1, "name": "Pull", "kind": "git_pull" },
    {
      "position": 2,
      "name": "Restart workers",
      "kind": "command",
      "command": "systemctl restart example-workers"
    },
    {
      "position": 3,
      "name": "Update nginx",
      "kind": "nginx",
      "config": {
        "subdomain": "workers",
        "upstream_port": 8001,
        "service_name": "example-workers"
      }
    }
  ]
}
```

---

## Server Configuration

Each service targets one of two pre-configured servers. Server credentials are set via environment variables:

```env
SERVER_1_HOST=localhost        # Use localhost for in-container execution
SERVER_1_USER=root
SERVER_1_PORT=22
SERVER_1_KEY_PATH=             # Leave empty for local subprocess

SERVER_2_HOST=110.239.81.246  # Real remote server
SERVER_2_USER=root
SERVER_2_PORT=3097
SERVER_2_KEY_PATH=/run/secrets/server_2_key   # Mounted SSH private key
```

To add a server's SSH key, generate a key pair and push it with `ssh-copy-id`:

```bash
ssh-keygen -t ed25519 -f secrets/server_2_key -N "" -C "seravops@server_2"
sshpass -p '<password>' ssh-copy-id -i secrets/server_2_key.pub -o StrictHostKeyChecking=no -p <port> root@<host>
```

Mount the key into the container by adding to `docker-compose.yml` volumes:
```yaml
- ./secrets/server_2_key:/run/secrets/server_2_key:ro
```

Add `secrets/` to `.gitignore` — private keys must never be committed.

`localhost`, `127.0.0.1`, and `::1` targets use a local subprocess instead of SSH — useful for development and tasks that run on the host running the app container.

Private keys must be mounted into the container; they must never be committed.

---

## Safe Nginx Config Updates

Nginx steps go through a 3-phase safety mechanism:

1. **Render** — the Jinja2 template `nginx/reverse_proxy.conf.j2` is filled with `subdomain`, `upstream_port`, and `service_name`
2. **Validate** — the rendered config is written to a temporary location and tested with `nginx -t -c /tmp/seravops-<name>-nginx.conf`
3. **Apply** — only if validation succeeds, the config is installed to `/etc/nginx/conf.d/<name>.conf` and `nginx -s reload` is called

A malformed config never replaces a working one. Validation failures are streamed to the execution log.

---

## Adding a New Step Kind

1. Add the value to `StepKind` in [`app/models/enums.py`](app/models/enums.py) and generate an Alembic migration
2. Implement the logic in `app/services/` (follow the `CommandResult` pattern)
3. Dispatch it from `_execute_step()` in [`app/services/recipe_service.py`](app/services/recipe_service.py)
4. Add Pydantic validation for required `config` keys in [`app/schemas/recipe.py`](app/schemas/recipe.py)
5. Add the kind option + fields block to the step builder in [`app/templates/recipes/new.html`](app/templates/recipes/new.html) and [`app/templates/recipes/edit.html`](app/templates/recipes/edit.html)

Keep all orchestration in `recipe_service.py`. Routers validate input, enforce role dependencies, invoke a service, and shape the response — nothing more.

---

## Execution Engine & Limitations

Executions run inside FastAPI `BackgroundTasks` — simple, process-local, zero-dependency. Implications:

- An app restart during a running recipe will interrupt it
- Only one app process can track executions (no distributed workers)
- Long-running or multi-server deployments may need a durable queue (e.g. Celery, ARQ, or a job table with a worker process)

See [`docs/architecture.md`](docs/architecture.md) for a deeper discussion.

---

## Production Deployment

```bash
# Build the slim runtime image (excludes dev/lint tools)
docker build --target runtime -t seravops:latest .
```

Run migrations as an explicit pre-traffic step:

```bash
docker run --rm --env-file .env seravops:latest alembic upgrade head
```

See [`docs/production.md`](docs/production.md) for a full production checklist.

---

## Further Reading

| Document | Description |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | System design, data flow, and component interactions |
| [`docs/recipes.md`](docs/recipes.md) | Authoring recipes and extending step kinds |
| [`docs/production.md`](docs/production.md) | Production hardening, secrets, and migration strategy |
| [`AGENT.md`](AGENT.md) | AI agent context: codebase map, conventions, and task guidance |
