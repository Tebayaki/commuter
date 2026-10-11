FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.14-slim AS builder

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system commuter \
    && useradd --system --gid commuter --home-dir /app commuter

COPY --from=builder --chown=commuter:commuter /app/.venv /app/.venv

USER commuter

CMD ["commuter"]
