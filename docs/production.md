# Production Deployment — Seravops

This document covers everything needed to run Seravops securely in a production environment.

---

## Pre-flight Checklist

Before routing any traffic to a production instance:

- [ ] `JWT_SECRET` is set to a long random string (minimum 32 characters)
- [ ] Default passwords (`admin123`, `developer123`) have been changed
- [ ] `DEBUG=false` (ensures cookies have `secure=True`)
- [ ] HTTPS is terminated by a reverse proxy (nginx, Caddy, etc.)
- [ ] The app is NOT exposed directly on port 7372 to the internet
- [ ] SSH private keys are mounted as Docker secrets, not baked into the image
- [ ] PostgreSQL uses a strong password and is not exposed to the internet
- [ ] Alembic migrations have been run before starting the new app version

---

## Building the Production Image

The Dockerfile has a `runtime` build target that excludes dev/lint dependencies:

```bash
docker build --target runtime -t seravops:latest .
```

This produces a slim image. Do not use the `development` target in production.

---

## Running Migrations

Always run migrations as a separate step before starting the new app container. Never have the app auto-migrate on startup.

```bash
docker run --rm \
  --env-file .env \
  seravops:latest \
  alembic upgrade head
```

Or with explicit env vars:

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://seravops:<password>@db:5432/seravops" \
  -e JWT_SECRET="<your-secret>" \
  seravops:latest \
  alembic upgrade head
```

---

## Environment Variables

| Variable | Required | Recommendation |
|---|---|---|
| `JWT_SECRET` | ✅ | Use `openssl rand -hex 32` to generate |
| `DATABASE_URL` | ✅ | Point to your production PostgreSQL |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | — | Default 480 (8h); reduce for sensitive environments |
| `DEBUG` | ✅ | Must be `false` in production |
| `SERVER_1_HOST` | ✅ | IP or hostname of your first managed server |
| `SERVER_1_USER` | ✅ | A dedicated deploy user (not root) |
| `SERVER_1_KEY_PATH` | ✅ | Path to mounted SSH private key |
| `SERVER_2_*` | — | If you have a second server |

---

## SSH Key Management

Private keys must be mounted into the container at runtime — never baked into the image.

**With Docker secrets (recommended):**

```yaml
# docker-compose.prod.yml
services:
  app:
    image: seravops:latest
    secrets:
      - server_1_key
    environment:
      SERVER_1_KEY_PATH: /run/secrets/server_1_key

secrets:
  server_1_key:
    file: ./secrets/server_1_key
```

**With volume mounts:**

```yaml
services:
  app:
    volumes:
      - /etc/seravops/keys/server_1:/run/keys/server_1:ro
    environment:
      SERVER_1_KEY_PATH: /run/keys/server_1
```

---

## Deploy User Permissions

The SSH user configured for each server should have **minimal permissions**. The exact requirements depend on which step kinds you use:

| Step Kind | Minimum permissions |
|---|---|
| `command` | Execute the specific commands in your recipes |
| `git_pull` | Read access to the git remote; write access to `app_path` |
| `nginx` | Write to `/etc/nginx/conf.d/`; run `nginx -s reload` (via sudoers) |

Example sudoers entry for nginx reload:

```
deploy ALL=(ALL) NOPASSWD: /usr/bin/nginx -s reload
deploy ALL=(ALL) NOPASSWD: /usr/bin/install -m 0644 /tmp/seravops-* /etc/nginx/conf.d/
```

Never grant unrestricted `root` SSH access to the deploy user.

---

## Reverse Proxy Configuration

Seravops should run behind nginx, Caddy, or another reverse proxy that handles TLS.

**Example nginx config:**

```nginx
server {
    listen 443 ssl;
    server_name seravops.internal.example.com;

    ssl_certificate     /etc/ssl/certs/seravops.crt;
    ssl_certificate_key /etc/ssl/private/seravops.key;

    location / {
        proxy_pass         http://127.0.0.1:7372;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # For HTMX polling — keep connections alive
        proxy_read_timeout 30s;
    }
}
```

---

## Health Check

The `/health` endpoint returns `{"status": "ok"}` with a 200 status when the application is running. Use it for load balancer or container health checks:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:7372/health"]
  interval: 10s
  timeout: 5s
  retries: 3
```

---

## Database Backup

Seravops stores all state in PostgreSQL. Implement regular backups using your platform's tools:

```bash
# Example: pg_dump to S3 via cron
pg_dump -U seravops seravops | gzip | aws s3 cp - s3://your-bucket/seravops-$(date +%Y%m%d).sql.gz
```

---

## Upgrading

1. Build the new image: `docker build --target runtime -t seravops:new .`
2. Run migrations against the production DB: `docker run --rm ... seravops:new alembic upgrade head`
3. Roll over the container: `docker compose up -d --no-deps app` (or your orchestration equivalent)
4. Verify with `/health` and a quick smoke test

> Note: Any in-flight recipe executions will be interrupted during a restart. The execution will remain in `running` state in the DB. Currently there is no automatic recovery — you may need to manually mark interrupted executions as `failed` or re-trigger them.

---

## Known Limitations in Production

| Limitation | Impact | Mitigation |
|---|---|---|
| `BackgroundTasks` is in-process | App restart kills running executions | Schedule deploys during low-traffic windows; or replace with a durable queue |
| Two servers hardcoded | Cannot manage more than 2 servers without code changes | Add a `servers` table and dynamic server resolution |
| No execution timeout | A hung SSH command blocks the asyncio event loop | Set SSH connection/exec timeouts in `asyncssh`; add step-level timeouts |
| No retry logic | A failed step requires manual re-trigger of the full recipe | Add step-level retry config to `RecipeStep` |
| No webhook triggers | Must manually trigger recipes via UI or API | Add `POST /webhooks/{service_slug}/trigger` with HMAC signature verification |
