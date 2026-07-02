# Seravops

Seravops is a FastAPI deployment/recipe orchestrator. It stores services and ordered
deployment steps, runs them locally or over SSH, and streams each step's output into
PostgreSQL for live HTMX polling. The application uses a pragmatic routers → services →
SQLAlchemy structure; there is no repository abstraction or separate frontend build.

## Start the development environment

Only Docker and Docker Compose are required. The web application uses port `7372` (`SERA`
on a telephone keypad).

```bash
cp .env.example .env
make up
make migrate
```

Open <http://localhost:7372>. The initial migration creates:

| Role | Username | Password |
| --- | --- | --- |
| Admin | `admin` | `admin123` |
| Developer | `developer` | `developer123` |

It also creates a **Seravops Demo** service and an **Update** recipe. At container startup,
the entrypoint creates a disposable Git origin and working copy under `/tmp`; the seeded
recipe performs a real `git pull --ff-only`, then runs a safe restart command. This makes
the login → select service → select recipe → run → live logs flow testable immediately.

Change the seeded passwords and `JWT_SECRET` before exposing the application outside a
local environment.

## Common commands

```bash
make up       # build and start app + PostgreSQL
make migrate  # run Alembic migrations
make test     # run pytest inside the app container
make lint     # run Ruff and Black checks
make logs     # follow application logs
make down     # stop containers
```

Interactive API documentation is at <http://localhost:7372/docs>. API clients can obtain a
Bearer token from `POST /auth/token`. Admin-only write endpoints use `require_admin`;
authenticated admins and developers can run recipes and view execution logs.

## Project layout

```text
app/
├── core/       # environment settings, JWT/RBAC, logging, dependencies
├── models/     # concrete SQLAlchemy 2.0 async models
├── routers/    # thin HTML/API request handlers
├── schemas/    # Pydantic v2 input/output models
├── services/   # recipe, SSH, Git, nginx, auth, and service logic
├── static/     # small hand-written stylesheet
├── templates/  # Jinja2 pages, HTMX fragment, and nginx template
├── db.py       # async engine and session factory
└── main.py     # FastAPI application factory
migrations/     # Alembic environment and revisions
tests/          # service-layer tests using async SQLite and mocked SSH execution
```

## Adding a recipe or step type

A recipe is a database record with ordered `RecipeStep` rows. Existing kinds are
`command`, `git_pull`, and `nginx`.

To add a recipe through the API, authenticate as an admin and `POST /recipes`:

```json
{
  "service_id": 1,
  "name": "Update workers",
  "description": "Pull and restart workers",
  "steps": [
    {"position": 1, "name": "Pull", "kind": "git_pull"},
    {
      "position": 2,
      "name": "Restart",
      "kind": "command",
      "command": "systemctl restart example-workers"
    }
  ]
}
```

To add a new kind in code:

1. Add the value to `StepKind` in `app/models/enums.py` and generate an Alembic migration.
2. Add and test the concrete operation in `app/services/`.
3. Dispatch it from `_execute_step()` in `app/services/recipe_service.py`.
4. Add Pydantic validation for its required `config` keys in `app/schemas/recipe.py`.

Keep orchestration in `recipe_service.py`; routers should only validate input, enforce the
role dependency, invoke a service, and shape the response.

## SSH execution and live logs

Each service selects `server_1` or `server_2`. The corresponding host, user, port, and key
path come from environment settings. Private keys should be mounted into the container and
referenced by path; they must not be committed.

The execution flow is:

1. `POST /executions/run` creates a `pending` execution and schedules a FastAPI
   `BackgroundTasks` coroutine.
2. The runner marks it `running`, loads the ordered steps, and resolves the target server.
3. `ssh_service` uses `asyncssh` remotely. A `localhost`, `127.0.0.1`, or `::1` target uses
   an async local subprocess, which is useful for development and deliberate on-host tasks.
4. Stdout and stderr are consumed concurrently. Every line opens a short database session
   and commits an `ExecutionLog` row immediately.
5. The browser polls `GET /executions/{id}` every two seconds with HTMX. That route returns
   the current status fragment for HTMX requests and a full page for normal navigation.
6. A non-zero step exit code stops the recipe and marks it `failed`; all zero exit codes
   mark it `success`.

`BackgroundTasks` is intentionally the first implementation. It is process-local: an app
restart can interrupt running recipes. Move this boundary to a durable queue before running
long deployments or multiple application replicas.

## Safe nginx configuration updates

Nginx steps render `app/templates/nginx/reverse_proxy.conf.j2` with `subdomain`,
`upstream_port`, and `service_name`. The rendered server block is written to a temporary
candidate file, not the active `conf.d` path. Seravops then creates an isolated temporary
nginx configuration which includes that candidate and runs:

```text
nginx -t -c /tmp/seravops-<service>-nginx.conf
```

If validation fails, the error is streamed to the execution log and the active nginx files
are untouched. Only a successful validation allows the candidate to be installed under
`/etc/nginx/conf.d/` and `nginx -s reload` to run. A malformed new site therefore cannot
replace an existing working configuration.

Remote deployment users need permission to write the target nginx config directory and
reload nginx. Prefer narrowly scoped privilege configuration rather than unrestricted root
SSH access.

## Production image

The default final Docker target is the slim `runtime` stage and excludes test/lint tools:
 
```bash
docker build --target runtime -t seravops:latest .
```

Run migrations as an explicit deployment step before routing traffic to a new application
revision.
