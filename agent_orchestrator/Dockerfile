# Dockerfile for the agent_orchestrator companion service.
# Lives in the same git repo as the fabric backend (so the
# hitl-context wrapper can be imported as a sibling editable install),
# but builds + deploys as a separate Fly app (tcs-agent-orchestrator).

FROM python:3.11-slim

WORKDIR /app

# Build deps for psycopg + bcrypt (transitive — the shared pyproject
# pulls them; the agent_orchestrator service itself doesn't talk to
# Postgres but we keep one pyproject.toml for both apps).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps. Same project layout as the fabric: install
# hitl-context first (editable, for the LLM wrapper), then the
# top-level project (which now also includes agent_orchestrator).
COPY pyproject.toml ./
COPY hitl-context/pyproject.toml ./hitl-context/pyproject.toml
COPY hitl-context/src/ ./hitl-context/src/
COPY hitl-context/docs/ ./hitl-context/docs/
COPY backend/ ./backend/
COPY agent_orchestrator/ ./agent_orchestrator/
RUN pip install --no-cache-dir -e ./hitl-context && \
    pip install --no-cache-dir -e .

EXPOSE 8002
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["uvicorn", "agent_orchestrator.main:app", "--host", "0.0.0.0", "--port", "8002"]
