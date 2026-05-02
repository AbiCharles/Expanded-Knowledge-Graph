# Multi-stage build: install deps in a builder, copy only what's needed
# into a slim runtime layer. Frontend is built separately and served as
# static assets (no node in the runtime image).

# ---------- Stage 1: frontend build ----------
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
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
RUN pip install --no-cache-dir -e ./hitl-context && \
    pip install --no-cache-dir -e .

# Bring in the built frontend as static assets
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Runtime config
EXPOSE 8001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
# JWT_SECRET MUST be set at run time. Fail fast if it isn't.
ENV JWT_SECRET=""

# Run uvicorn with sane production defaults — no --reload, single worker
# (the in-process state means horizontal scale needs Redis first).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
