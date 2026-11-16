FROM python:3.14.10-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
RUN uv sync --locked --no-dev --no-editable

RUN useradd --system --uid 10001 --no-create-home concilia
USER concilia

CMD ["uvicorn", "concilia.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
