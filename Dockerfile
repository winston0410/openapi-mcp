FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./

RUN uv sync --locked --no-dev

COPY ./ ./

RUN groupadd -r appuser && useradd -m -r -g appuser appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/app/.venv/bin/python", "-m", "main"]
