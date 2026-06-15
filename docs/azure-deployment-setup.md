# Azure deployment — environment configuration

The repo's `.env.example` documents every variable the backend reads.
This doc covers **how to push those values into a running Azure
deployment** so the app on `main` / `dev` / `Development` branches
all connect to Neo4j (and the LLM, JWT, etc.) the same way the Fly
deployment does today.

The repo itself never contains real secrets — branches just hold
source. The values live on whatever runtime executes the app.

---

## The full required set

If you set the seven secrets below, the deployment matches what's
running on Fly today.

| Variable | Purpose | Required? |
|---|---|---|
| `JWT_SECRET` | Server-side signing key for auth tokens. **Backend refuses to start without one.** Generate fresh per environment: `openssl rand -hex 32`. | Yes |
| `LLM_PROVIDER` | `openai` \| `azure` \| `fake`. Use `fake` for demos that don't need real LLM calls. | Yes |
| `OPENAI_API_KEY` | OpenAI API key (only when `LLM_PROVIDER=openai`). | Conditional |
| `HITL_ADMIN_PASSWORD` | The admin login password the seeded admin user gets. Don't leave this as the default in any environment a stakeholder can reach. | Yes |
| `NEO4J_URI` | `bolt://hostname:7687` for the shared Neo4j. | Yes (for graph) |
| `NEO4J_USER` | Neo4j username (typically `neo4j`). | Yes (for graph) |
| `NEO4J_PASSWORD` | Neo4j password. | Yes (for graph) |

Optional add-ons: `NEO4J_DATABASE` (Enterprise multi-DB), `CORS_ORIGINS` (defaults to localhost dev),
`LOG_LEVEL`, `HITL_MAX_VECTOR_CHUNKS`, the Azure OpenAI variants.

---

## Step 1 — read the current values off the Fly deployment

Since `main` and `dev` and `Development` all share one Neo4j (your
chosen topology), you only need to pull each value **once** and reuse
it across all three Azure branches' deployments.

Open a shell where the Fly CLI is authenticated and run:

```bash
# List which secrets exist (names only — Fly never prints values).
fly secrets list -a tcs-knowledge-fabric

# Read the actual values out of the running machine's env.
# (Fly secrets are exposed as env vars to the container at runtime.)
fly ssh console -C "env | grep -E '^(JWT_SECRET|LLM_PROVIDER|OPENAI_API_KEY|HITL_ADMIN_PASSWORD|NEO4J_)='"
```

Copy these into a **scratch text file you keep locally** (do not commit
it). You'll paste them into Azure in the next step.

---

## Step 2 — push the values into the Azure runtime

Pick the section that matches your Azure runtime. **In all three
cases, the env vars get set per-deployment, not per-branch**: a single
runtime resource holds them and serves whichever branch is currently
deployed to it. If you want per-branch isolation, you'll have three
runtime resources (e.g. three App Services), each with its own env-var
config — but they can all hold the same NEO4J values.

### Option A — Azure App Service

The simplest path; the most common runtime for Python web apps.

```bash
# Set this group once per App Service. Repeat for the dev and Development
# App Services if you have separate ones.
APP_NAME="tcs-knowledge-fabric"          # your App Service name
RG="your-resource-group"

az webapp config appsettings set \
  --resource-group "$RG" \
  --name "$APP_NAME" \
  --settings \
    JWT_SECRET="<value-from-fly>" \
    LLM_PROVIDER="openai" \
    OPENAI_API_KEY="<value-from-fly>" \
    HITL_ADMIN_PASSWORD="<value-from-fly>" \
    NEO4J_URI="<value-from-fly>" \
    NEO4J_USER="<value-from-fly>" \
    NEO4J_PASSWORD="<value-from-fly>"

# Restart so the new env vars are picked up.
az webapp restart --resource-group "$RG" --name "$APP_NAME"
```

**Or via the Azure portal:**

1. Navigate to **App Service → Settings → Environment variables → Application settings**.
2. Click **+ Add** for each variable. Mark each as a **deployment slot setting** if you want the values to follow the slot rather than the code (recommended for secrets).
3. Click **Save** at the top.
4. App Service auto-restarts; first request may be a cold start.

### Option B — Azure Container Apps

If you're running the backend as a container (matches the Fly setup
shape — Dockerfile, image registry):

```bash
APP_NAME="tcs-knowledge-fabric"           # your Container App name
RG="your-resource-group"

# Container Apps treat env vars and secrets separately. Sensitive
# values go in --secrets first, then referenced via env vars.
az containerapp secret set \
  --name "$APP_NAME" --resource-group "$RG" \
  --secrets \
    jwt-secret="<value>" \
    openai-key="<value>" \
    hitl-admin-pw="<value>" \
    neo4j-pw="<value>"

az containerapp update \
  --name "$APP_NAME" --resource-group "$RG" \
  --set-env-vars \
    JWT_SECRET=secretref:jwt-secret \
    LLM_PROVIDER=openai \
    OPENAI_API_KEY=secretref:openai-key \
    HITL_ADMIN_PASSWORD=secretref:hitl-admin-pw \
    NEO4J_URI="<bolt://host:7687>" \
    NEO4J_USER="<neo4j>" \
    NEO4J_PASSWORD=secretref:neo4j-pw

# The update triggers a new revision automatically; no restart needed.
```

### Option C — Azure Kubernetes Service (AKS)

If the cluster runs the app, put NEO4J values in a Kubernetes secret
and reference it from the deployment manifest:

```bash
NAMESPACE="default"   # or whichever namespace holds the workload

kubectl create secret generic kf-secrets -n "$NAMESPACE" \
  --from-literal=JWT_SECRET="<value>" \
  --from-literal=OPENAI_API_KEY="<value>" \
  --from-literal=HITL_ADMIN_PASSWORD="<value>" \
  --from-literal=NEO4J_URI="<bolt://host:7687>" \
  --from-literal=NEO4J_USER="<value>" \
  --from-literal=NEO4J_PASSWORD="<value>" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then in the deployment spec:

```yaml
containers:
- name: backend
  envFrom:
    - secretRef:
        name: kf-secrets
  env:
    - name: LLM_PROVIDER
      value: openai
```

After `kubectl apply`, roll the deployment:

```bash
kubectl rollout restart deployment/tcs-knowledge-fabric -n "$NAMESPACE"
```

---

## Step 3 — handle multiple branches

You picked "share one Neo4j across `main` / `dev` / `Development`",
so each branch's deployment uses **identical Neo4j credentials**. The
config pattern depends on whether each branch has its own runtime or
they share one:

| Layout | What to do |
|---|---|
| **One runtime per branch** (e.g. three App Services or three slots: `prod`, `staging`, `dev`) | Apply Step 2 commands against each runtime. Same NEO4J_* values; can differ on JWT_SECRET so token leaks don't cross environments. |
| **One runtime, branches deploy in sequence** | Step 2 is one-time setup. Whatever branch is currently deployed picks up the shared env config. |
| **Azure DevOps Pipelines deploying to runtimes** | Store NEO4J_* in an Azure DevOps **Variable Group** (Library → Variable Groups → mark variables as secret). Reference the group from each branch's pipeline. The pipeline injects them at deploy time. |

For the third pattern (Variable Group) — recommended if you have CI/CD:

```yaml
# In azure-pipelines.yml
variables:
  - group: kf-shared-secrets   # contains NEO4J_URI/USER/PASSWORD/etc.
```

Branch policies can then enforce that `main` pipelines pull a
production-flavoured Variable Group while `dev`/`Development`
pipelines pull a development one.

---

## Step 4 — verify the connection from the running app

After applying any of the patterns above, restart (App Service) or
let the rolling update complete (Container Apps / AKS). Then exec
into the running container and run the same probe we ran for Fly:

```bash
# App Service — Bash session into the running container.
az webapp ssh --resource-group "$RG" --name "$APP_NAME"

# Container Apps — exec into the running revision.
az containerapp exec --name "$APP_NAME" --resource-group "$RG"

# AKS — pick a pod, exec.
kubectl exec -it -n "$NAMESPACE" deploy/tcs-knowledge-fabric -- bash
```

Then inside the container:

```bash
python3 -c "
import os, sys
sys.path.insert(0, '/app')
from backend.datasources import DataSourceRegistry
from pathlib import Path

ds = DataSourceRegistry.from_yaml(
    storage_path=Path('/app/backend/data/sources.yaml'),
    project_root=Path('/app'),
    openai_api_key=os.environ.get('OPENAI_API_KEY'),
)
neo4j = ds.get('neo4j_default')
if neo4j is None:
    print('FAIL: neo4j_default not registered. Check NEO4J_URI / USER / PASSWORD env vars.')
else:
    res = neo4j.test_connection(
        os.environ['NEO4J_URI'], os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD']
    )
    print('Neo4j connectivity:', res)
"
```

Expected output: `Neo4j connectivity: (True, 'connected')`.

If you get an authentication error, the password didn't make it
through (check the Azure resource's env config). If you get a
network error, the bolt port may be blocked — Neo4j Aura URIs
need outbound 7687 open from the Azure compute.

---

## Security checklist

- [ ] **Never commit a real `.env`.** `.env` is in `.gitignore`; verify
      with `git check-ignore .env`.
- [ ] **Mark secrets as secret** in the Azure resource (App Service:
      tick "Slot setting" + don't expose to the public web; Container
      Apps: use `secretref:` not raw env vars; AKS: use a Kubernetes
      Secret, not a ConfigMap).
- [ ] **Rotate `JWT_SECRET` per environment.** A leak in `Development`
      shouldn't grant tokens valid in `main`.
- [ ] **Restrict who can read the Azure resource's configuration.**
      Anyone with read access to Application Settings can see the raw
      secret values. Use RBAC tightly.
- [ ] **Consider Azure Key Vault** for production. The App
      Service / Container Apps / AKS patterns above all support
      `@Microsoft.KeyVault(SecretUri=...)` references that pull from
      a Key Vault at runtime instead of storing the value in the
      resource's own config.

---

## What about local development?

If a developer on the team is cloning the Azure repo to work locally,
they should:

1. Copy `.env.example` to `.env` in the repo root.
2. Fill in the values they need (`fake` for `LLM_PROVIDER` is
   usually fine; Neo4j optional if they're not touching graph
   scenarios).
3. Run `docker compose up` (the compose file reads `.env`) or
   `source .env && uvicorn backend.main:app`.

The `.env` file is gitignored — each developer's local config is
their own.
