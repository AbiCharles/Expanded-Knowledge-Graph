# Multi-stage build: install deps in a builder, copy only what's needed
# into a slim runtime layer. Frontend is built separately and served as
# static assets (no node in the runtime image).

# ---------- Stage 1: frontend build ----------
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# W8 — bake the agent-orchestrator URL into the bundle. fly.toml passes
# VITE_AGENT_ORCHESTRATOR_URL via [build.args]; ARG→ENV forwarding here
# is what makes Vite pick it up. Empty default = falls back to
# localhost:8002 (api.ts), which is what dev expects.
ARG VITE_AGENT_ORCHESTRATOR_URL=
ENV VITE_AGENT_ORCHESTRATOR_URL=$VITE_AGENT_ORCHESTRATOR_URL
RUN npm run build

# ---------- Stage 2: backend ----------
FROM python:3.11-slim AS backend
WORKDIR /app

# System deps for psycopg + bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps from the project's pyproject.toml
COPY pyproject.toml ./
COPY hitl-context/pyproject.toml ./hitl-context/pyproject.toml
COPY hitl-context/src/ ./hitl-context/src/
COPY hitl-context/docs/ ./hitl-context/docs/
COPY backend/ ./backend/
# Local RCA vision/RAG service — runs as a co-process on :8000 (started by
# docker-entrypoint.sh) so the fabric's rca_vision / rca_knowledge http
# sources resolve in-cluster. Point base_url at a real RCA_agent to swap it.
COPY rca_service/ ./rca_service/
# Ship the Neo4j seed (cypher + python applier) alongside the backend so
# operators can re-seed the supply-chain graph from inside the container
# when Aeronova / SUP-021 entities are missing. Run from /app:
#   python3 share/tcs_kf_graph_data/seed_neo4j.py
COPY share/tcs_kf_graph_data/ ./share/tcs_kf_graph_data/
# Launcher wireframe served at /launcher (no auth). Self-contained HTML
# that emits an instance.yaml the operator can hand to bin/kf-launch.
COPY docs/launcher-wireframe.html ./docs/launcher-wireframe.html
RUN pip install --no-cache-dir -e ./hitl-context && \
    pip install --no-cache-dir -e .

# Bring in the built frontend as static assets
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Snapshot the seeded data dir to /app/seed_data so the entrypoint can
# re-seed an empty Fly-style volume on first boot. See docker-entrypoint.sh.
RUN cp -R /app/backend/data /app/seed_data

# Entrypoint handles first-run volume seeding, then execs the CMD.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Runtime config
EXPOSE 8001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
# JWT_SECRET MUST be set at run time. Fail fast if it isn't.
ENV JWT_SECRET=""

ENTRYPOINT ["docker-entrypoint.sh"]
# Run uvicorn with sane production defaults — no --reload, single worker
# (the in-process state means horizontal scale needs Redis first).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
