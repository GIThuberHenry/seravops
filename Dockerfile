FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip wheel --wheel-dir /wheels ".[dev]"


FROM python:3.12-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates git nginx \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels seravops

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
RUN chmod +x /app/scripts/*.sh

EXPOSE 7372
ENTRYPOINT ["/app/scripts/bootstrap-demo.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7372"]


FROM runtime-base AS runtime
RUN rm -rf /wheels


FROM runtime-base AS development
RUN pip install --no-cache-dir --no-index --find-links=/wheels "seravops[dev]" \
    && rm -rf /wheels
COPY tests ./tests
