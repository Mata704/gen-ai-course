FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY sessions ./sessions
COPY projects ./projects
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "--app-dir", "sessions/course-01-ai-fundamentals/08-container-integration/starter/app", "api:app", "--host", "0.0.0.0", "--port", "8000"]
