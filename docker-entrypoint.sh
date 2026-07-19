#!/bin/sh
# Seed /app/backend/data from /app/seed_data on each boot.
#
# Why two phases:
#   - Reference data shipped in the image (CSVs, sources.yaml, ontologies/
#     mappings, scenarios) MUST refresh on every deploy so dataset and
#     scenario edits propagate. Otherwise the volume's stale copy hides them.
#   - User data (app.sqlite, uploads/, governance.sqlite once an operator has
#     mutated it, actions/) MUST be preserved across deploys.
#
# Strategy: explicit allow-list of "always refresh from seed" patterns
# (overwrites with -f), then a no-clobber pass (`cp -Rn`) to initialize any
# remaining files on first boot only.
set -e

SEED=/app/seed_data
DATA=/app/backend/data

if [ -d "$SEED" ]; then
  mkdir -p "$DATA"

  # ---- always-refresh (read-only reference data from the image) ----
  # Top-level CSVs (shipments, carriers, lanes, ports, events, performance,
  # products, sanctions).
  cp -f "$SEED"/*.csv "$DATA"/ 2>/dev/null || true
  # sources.yaml: registry of data sources (immutable in the demo flow;
  # operator-added sources go through the API and persist in app.sqlite,
  # not here).
  if [ -f "$SEED/sources.yaml" ]; then
    cp -f "$SEED/sources.yaml" "$DATA/sources.yaml"
  fi
  # Seed scripts that some demos run from inside the container.
  cp -f "$SEED"/*.py "$DATA"/ 2>/dev/null || true
  cp -f "$SEED"/*.sql "$DATA"/ 2>/dev/null || true
  # Cypher seed for the Neo4j graph. Operator must still run
  # seed_neo4j.py manually (the script targets the separate Fly Neo4j
  # app), but the source file should track image edits so the next
  # manual run picks them up without a force-cp SSH workaround.
  cp -f "$SEED"/*.cypher "$DATA"/ 2>/dev/null || true
  # actions/ subdir: write-action definitions. Edits to these YAMLs (new
  # actions, fixed validation) need to land on every deploy. The Action
  # registry parses *.yaml at boot; stale files there cause silent skips.
  if [ -d "$SEED/actions" ]; then
    mkdir -p "$DATA/actions"
    cp -f "$SEED/actions"/*.yaml "$DATA/actions/" 2>/dev/null || true
  fi

  # logistics.sqlite has a schema that evolves (Phase 2 = bookings; Phase 3
  # added demurrage_charges). Run the seed script if EITHER (a) the file
  # doesn't exist yet OR (b) a required table is missing. This protects
  # operator mutations to bookings while still letting new tables land on
  # the volume without a manual SSH step. The seed script is idempotent.
  if [ -f "$DATA/seed_logistics.py" ]; then
    need_seed=0
    if [ ! -f "$DATA/logistics.sqlite" ]; then
      need_seed=1
    else
      # Probe for the most-recently-added table. Add new probes here as
      # the schema grows.
      python3 -c "import sqlite3; sqlite3.connect('$DATA/logistics.sqlite').execute('SELECT 1 FROM demurrage_charges LIMIT 1')" 2>/dev/null || need_seed=1
    fi
    if [ "$need_seed" = "1" ]; then
      echo "[entrypoint] seeding logistics.sqlite (new file or missing table)…"
      (cd /app && python3 backend/data/seed_logistics.py) || true
    fi
  fi

  # ---- initialize-once (preserve operator/user mutations) ----
  # Everything else from the seed snapshot lands here only if not already
  # present on the volume — app.sqlite, uploads/, governance.sqlite,
  # policy_corpus/, policy_corpus.npz, actions/, etc.
  cp -Rn "$SEED"/. "$DATA"/ 2>/dev/null || true
fi

# Start the local RCA vision/RAG service (co-process) on 127.0.0.1:8000 so the
# fabric's rca_vision / rca_knowledge http sources resolve in-cluster. The
# vision Defect + PriorNCR/CAPARecommendation bindings and the C-scan image
# come from here. Best-effort — the fabric degrades gracefully if it's down.
if [ -d /app/rca_service ]; then
  echo "[entrypoint] starting RCA vision/RAG service on :8000…"
  (cd /app && python3 -m uvicorn rca_service.main:app --host 127.0.0.1 --port 8000 \
      >/tmp/rca_service.log 2>&1 &)
fi

exec "$@"
