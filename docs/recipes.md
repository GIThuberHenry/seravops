# Authoring Recipes — Seravops

Recipes are the core unit of work in Seravops. This document covers how to create them, what each step kind does, and how to extend the system with a new step kind.

---

## What is a Recipe?

A recipe is a **named, ordered list of steps** attached to a specific service. When triggered, steps execute sequentially. If any step exits with a non-zero code, the recipe is marked `failed` and subsequent steps are skipped.

Every recipe belongs to exactly one **Service**, which determines:
- The **target server** the steps run on (`server_1` or `server_2`)
- The **working directory** (`app_path`) used by `command` and `git_pull` steps

---

## Step Kinds

### `command`

Runs an arbitrary shell command in the service's `app_path` on the target server.

```json
{
  "position": 1,
  "name": "Install dependencies",
  "kind": "command",
  "command": "pip install -r requirements.txt"
}
```

The command is executed as:
```bash
cd <app_path> && <command>
```

- Use `&&` for chaining: `pip install -r requirements.txt && alembic upgrade head`
- The user must have permission to run the command on the target server
- stdout and stderr are both captured and streamed to the execution log

### `git_pull`

Runs `git pull --ff-only` in the service's `app_path`. No additional config required.

```json
{
  "position": 1,
  "name": "Pull latest code",
  "kind": "git_pull"
}
```

Equivalent to:
```bash
git -C <app_path> pull --ff-only
```

- If the pull would create a merge commit (non-fast-forward), it exits with a non-zero code and stops the recipe
- The deploy user must have read access to the git remote

### `nginx`

Renders an nginx reverse proxy config, validates it with `nginx -t`, and applies it only if validation passes.

```json
{
  "position": 3,
  "name": "Configure nginx",
  "kind": "nginx",
  "config": {
    "subdomain": "api",
    "upstream_port": 8000,
    "service_name": "my-api"
  }
}
```

Required `config` keys:

| Key             | Type   | Description                                       |
|-----------------|--------|---------------------------------------------------|
| `subdomain`     | string | The subdomain prefix (e.g. `api` → `api.example.com`) |
| `upstream_port` | int    | The local port the application listens on         |
| `service_name`  | string | Used as the config filename (`/etc/nginx/conf.d/<service_name>.conf`) |

The deploy user needs write access to `/etc/nginx/conf.d/` and permission to run `nginx -s reload`.

---

## Creating a Recipe via the Web UI (Admin)

1. Log in as an admin and navigate to a service (`/services`)
2. Click **New Recipe** (top-right of the recipe list)
3. Fill in the recipe name and optional description
4. Click **+ Add Step** to add steps:
   - Select the **kind** — the form fields update automatically
   - For `command`: type the shell command
   - For `git_pull`: no extra fields required
   - For `nginx`: fill in subdomain, upstream port, and service name
5. Repeat for each step, then click **Create Recipe**

Validation errors are shown inline; the form retains all your input so you can correct and resubmit.

---

## Creating a Recipe via API

```bash
TOKEN=$(curl -s -X POST http://localhost:7372/auth/token \
  -d "username=admin&password=admin123" | jq -r .access_token)

curl -X POST http://localhost:7372/recipes \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "service_id": 1,
    "name": "Full Deploy",
    "description": "Pull, install dependencies, migrate, reload nginx",
    "steps": [
      { "position": 1, "name": "Pull code", "kind": "git_pull" },
      { "position": 2, "name": "Install deps", "kind": "command", "command": "pip install -r requirements.txt" },
      { "position": 3, "name": "Migrate DB", "kind": "command", "command": "alembic upgrade head" },
      { "position": 4, "name": "Restart app", "kind": "command", "command": "systemctl restart myapp" },
      {
        "position": 5,
        "name": "Configure nginx",
        "kind": "nginx",
        "config": { "subdomain": "api", "upstream_port": 8000, "service_name": "myapp" }
      }
    ]
  }'
```

---

## Triggering a Recipe

**Via web UI:** Navigate to a service → click a recipe → click "Run".

**Via API:**
```bash
curl -X POST http://localhost:7372/executions/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "recipe_id=1"
```

Returns a redirect to `/executions/{id}`. Poll `GET /api/executions/{id}` for status and logs.

---

## Adding a New Step Kind

Follow these steps to extend Seravops with a new kind of deployment step.

### 1. Add the enum value

In `app/models/enums.py`:

```python
class StepKind(StrEnum):
    COMMAND = "command"
    GIT_PULL = "git_pull"
    NGINX = "nginx"
    MY_NEW_KIND = "my_new_kind"   # ← add here
```

### 2. Generate a migration

```bash
docker compose exec app alembic revision --autogenerate -m "add my_new_kind step kind"
make migrate
```

### 3. Implement the service function

In `app/services/my_new_kind_service.py`:

```python
from app.core.config import ServerConfig
from app.services import ssh_service
from app.services.ssh_service import CommandResult, OutputHandler


async def do_thing(
    target: ServerConfig,
    on_output: OutputHandler,
    **config,
) -> CommandResult:
    command = f"my-tool {config['required_param']}"
    return await ssh_service.execute(command, target, on_output)
```

### 4. Dispatch from `_execute_step()`

In `app/services/recipe_service.py`:

```python
from app.services import git_service, nginx_service, ssh_service, my_new_kind_service

async def _execute_step(step: RecipeStep, recipe: Recipe, on_output: Callable) -> CommandResult:
    service = recipe.service
    target = get_settings().server(service.target_server)
    if step.kind == StepKind.GIT_PULL:
        return await git_service.pull(service.app_path, target, on_output)
    if step.kind == StepKind.NGINX:
        return await nginx_service.validate_and_apply(target=target, on_output=on_output, **step.config)
    if step.kind == StepKind.MY_NEW_KIND:                    # ← add dispatch
        return await my_new_kind_service.do_thing(target=target, on_output=on_output, **step.config)
    command = f"cd {shlex.quote(service.app_path)} && {step.command}"
    return await ssh_service.execute(command, target, on_output)
```

### 5. Update the step builder frontend

In `app/templates/recipes/new.html`, add a new `kind-fields` block inside the `<template>` for your kind, and add the option to the `<select>`:

```html
<!-- Inside the step <template> -->
<select name="steps[__IDX__][kind]" class="kind-select">
  <option value="git_pull">git_pull — Pull latest code</option>
  <option value="command">command — Run a shell command</option>
  <option value="nginx">nginx — Update nginx config</option>
  <option value="my_new_kind">my_new_kind — Description</option>  <!-- add this -->
</select>

<!-- Add the fields block -->
<div class="kind-fields" data-for="my_new_kind" hidden>
  <label>
    Required Param
    <input name="steps[__IDX__][required_param]" placeholder="value">
  </label>
</div>
```

Also update the server-side form parser in `app/routers/recipes.py` to extract and pass the new field into `config`.

### 6. Write tests

In `tests/test_recipe_service.py`, follow the existing pattern:

```python
async def test_recipe_with_my_new_kind(async_session, session_factory):
    # create service, recipe with MY_NEW_KIND step
    # mock ssh_service.execute
    # assert execution succeeds / logs contain expected output
    ...
```

---

## Recipe Best Practices

- **Order matters**: Steps run sequentially; a failure stops the recipe
- **Idempotency**: Prefer commands that are safe to re-run (e.g. `pip install`, `alembic upgrade head`)
- **Atomicity**: Group steps that must succeed together in a single recipe
- **Separate recipes for separate environments**: Create one recipe per deployment stage rather than one mega-recipe with conditionals
- **Keep `command` steps short**: Long-running commands block the asyncio event loop; consider breaking them into multiple steps or moving to a durable queue
