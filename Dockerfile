FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

RUN groupadd --system commuter \
    && useradd --system --gid commuter --home-dir /app commuter \
    && chown -R commuter:commuter /app

USER commuter

CMD ["commuter"]
