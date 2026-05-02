# Production deployment guide

This document covers what to set, what to verify, and what to know
before pointing real users at this app. Skim it once before deploying;
come back to specific sections as you address each gap.

The companion document [scaling.md](scaling.md) covers feature-side
scaling (scenario sprawl, no-match UX, auto-generation). This file is
infra and security only.

---

## Required configuration

The backend **refuses to start** unless `JWT_SECRET` is set to a real
value. Generate one once:

```bash
openssl rand -hex 32
```

Set it in your deployment environment alongside the other config:

```bash
JWT_SECRET=<the long hex string from openssl>
LLM_PROVIDER=openai            # or azure or fake
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
CORS_ORIGINS=https://hitl.your-domain.com
```

### Azure OpenAI

Flip `LLM_PROVIDER=azure` and set:

```bash
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=<your-chat-deployment-name>
# Optional — only required if you use vector-store data sources:
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<your-embeddings-deployment-name>
```

`AZURE_OPENAI_DEPLOYMENT` is the chat deployment (typically a GPT-4 family
model). `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` is a *separate* deployment of
an embeddings model (e.g. `text-embedding-3-small`); without it the vector
store skips embedding and `resolve()` returns empty — chat keeps working.

For transient local runs where you really don't want to set a secret
(e.g. spinning up a one-off container to inspect the schema), export
`HITL_ALLOW_DEFAULT_SECRET=1`. The app boots with a loud warning that
tokens are forgeable. **Never use this in any real deployment.**

---

## Quick start with Docker

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)" > .env.docker
echo "DOMAIN=hitl.your-domain.com" >> .env.docker
echo "OPENAI_API_KEY=sk-..." >> .env.docker
docker compose --env-file .env.docker up -d
```

This brings up:

- `hitl-backend` — uvicorn on port 8001 (internal)
- `hitl-caddy` — auto-TLS reverse proxy on 80 + 443

The `hitl-data` volume holds the SQLite DB, the operator-uploaded data
sources, and the vector embedding cache. Back this up.

---

## Security checklist before going live

In rough order of how badly each one bites if skipped:

### 1. Real `JWT_SECRET`
Already enforced — the backend refuses to start without it. Don't share
this secret across environments; each deploy gets its own.

### 2. Change the default admin password
First thing you do after the first boot:

```bash
curl -X POST https://hitl.your-domain.com/api/auth/login \
  -d "username=admin&password=admin" \
  -H "content-type: application/x-www-form-urlencoded"
# → grab the token

curl -X POST https://hitl.your-domain.com/api/auth/change-password \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{"current_password": "admin", "new_password": "<a strong one>"}'
```

Better: use the UI, which has a sign-in flow at the root URL.

### 3. HTTPS (TLS termination)
The bundled `Caddyfile` auto-issues a Let's Encrypt cert for the
`DOMAIN` you set. If you have your own reverse proxy (nginx, ELB,
Cloud Run, etc.), terminate TLS there and point at `:8001`.

**Bearer tokens over plain HTTP are only safe on `localhost`.**

### 4. Rate limiting
Already on for `/api/auth/login` and `/api/auth/register` (10/minute
per source IP). Other endpoints rely on the app-wide 120/minute
default. Consider tightening at the reverse-proxy layer too — Caddy
and nginx both have native rate-limit modules.

### 5. Read-only DB user for the Query playground
The Query playground accepts arbitrary SQL from authenticated users.
Multi-statement input is refused, but a malicious user with a valid
account could still craft expensive single-statement queries. If your
governance store is critical:

- Create a read-only DB user (`CREATE USER hitl_ro WITH PASSWORD ... GRANT SELECT ON ALL TABLES IN SCHEMA public TO hitl_ro`).
- Register the source with that user's credentials, not the app's main
  DB user.

### 6. Backups
The `hitl-data` Docker volume contains:

- `app.sqlite` — cases + lineage events + users
- `sources.yaml` — registered data sources
- `uploads/` — operator-uploaded CSVs
- `*.npz` — vector embedding caches (regenerable)

Snapshot the volume daily. SQLite is single-file; `cp app.sqlite
app.sqlite.bak` is a valid backup as long as the app isn't writing.
For an online backup: `sqlite3 app.sqlite ".backup app.sqlite.bak"`.

### 7. LLM cost ceiling
- Vector store registration is capped at 500 chunks per source by
  default; override with `HITL_MAX_VECTOR_CHUNKS=N` if you really need
  to.
- Per-user case creation is rate limited globally. Tighten this for
  high-stakes deployments.
- OpenAI itself has spending limits — set them.

---

## Things this build does *not* yet handle

These are deliberate trade-offs documented so you can decide which to
tackle first:

| Gap | When it bites | What to do |
|---|---|---|
| **Single uvicorn worker** | Restart drops in-flight SSE streams; horizontal scale has divergent in-process state | Move case-store + decision events to Redis; switch to AsyncQueueTransport with Kafka/SQS |
| **No password reset** | Users locked out if they forget passwords | Wire SMTP, add `/auth/reset-request` + `/auth/reset-confirm` endpoints |
| **No email verification** | Anyone with an account name can register | Add a verification step before activating new accounts |
| **No audit log retention policy** | Lineage table grows unboundedly | Add a daily cron that archives lineage > 90 days to S3 |
| **No structured logging** | Hard to grep log files for incidents | Switch to structlog or python-json-logger |
| **No metrics emission** | Can't alert on regressions | Wire Prometheus instrumentation (FastAPI has good plugins) |

The framework's `LineageRecorder` Protocol is designed to be swapped
for a structured logger that emits to your governance audit store —
that one swap covers ingestion + retention + queryability all at once.

---

## CI / operational hygiene

GitHub Actions workflow at `.github/workflows/ci.yaml` runs on every
push and PR:

- `framework-tests` — the framework's `verify_package.py` (90/90)
- `backend-tests` — the pytest suite (21 tests)
- `frontend-build` — `npm run build` (typecheck + bundle)
- `ruff-lint` — Python lint

Add branch protection on `main` requiring all four jobs to pass before
merge.

---

## Smoke-test checklist after deploy

1. `curl https://hitl.your-domain.com/api/health` → `{"status":"ok"}`
2. Sign in via the UI as admin (default `admin/admin` until step 2 of
   the security checklist above).
3. Click a suggested-prompt chip → confirm → watch the envelope fill →
   reach the Teams card → reject. Lineage panel pulses for every step.
4. Open Metrics → see the case you just ran in the totals.
5. Restart the backend (`docker compose restart backend`). Refresh the
   UI. Your case is still there with its full lineage.
