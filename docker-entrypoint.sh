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
  # actions/ subdir: write-action definitions. Edits to these YAMLs (new
  # actions, fixed validation) need to land on every deploy. The Action
  # registry parses *.yaml at boot; stale files there cause silent skips.
  if [ -d "$SEED/actions" ]; then
    mkdir -p "$DATA/actions"
    cp -f "$SEED/actions"/*.yaml "$DATA/actions/" 2>/dev/null || true
  fi

  # ---- initialize-once (preserve operator/user mutations) ----
  # Everything else from the seed snapshot lands here only if not already
  # present on the volume — app.sqlite, uploads/, governance.sqlite,
  # policy_corpus/, policy_corpus.npz, actions/, etc.
  cp -Rn "$SEED"/. "$DATA"/ 2>/dev/null || true
fi

exec "$@"
