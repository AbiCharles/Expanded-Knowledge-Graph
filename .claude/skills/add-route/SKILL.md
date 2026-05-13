---
name: add-route
description: Scaffold a new FastAPI endpoint following the project's conventions. Usage: /add-route <METHOD> <path>. Example: /add-route POST /widgets/{id}/promote
---

# Add a new FastAPI route: $1 $2

The project's API layer is a thin set of routers under `backend/api/`, all mounted under `/api` in `backend/main.py`. Apply the established pattern.

## Conventions

1. **File location**: `backend/api/<group>.py`, where `<group>` is the first path segment (`/widgets/...` → `backend/api/widgets.py`). If the file exists, append; otherwise create.

2. **Router module skeleton** (for new files):

   ```python
   """One-sentence description of this group's endpoints."""
   from __future__ import annotations

   from fastapi import APIRouter, Depends, HTTPException, Request
   from pydantic import BaseModel

   from ..auth import CurrentUser, current_user

   router = APIRouter(tags=["<group>"])
   ```

3. **Handler shape** (mirror `backend/api/scenarios.py`):

   ```python
   @router.<method>("<sub-path>")
   def <handler>(request: Request, user: CurrentUser = Depends(current_user)) -> <ResponseModel>:
       state = request.app.state.app_state
       ...
   ```

   - Always access services via `request.app.state.app_state` — no module-level globals.
   - Auth via `Depends(current_user)` is the default; omit only if the endpoint is intentionally public (and document why in the docstring).
   - For form/file inputs that involve `OAuth2PasswordRequestForm`, pass the class explicitly: `Depends(OAuth2PasswordRequestForm)`. See [backend/api/auth.py:105](backend/api/auth.py#L105) for why bare `Depends()` is brittle here.

4. **Pydantic models** for request/response shapes — define at the top of the router file.

5. **Register the router** in `backend/main.py` (only for new files):
   - Add: `from .api.<group> import router as <group>_router`
   - Add: `app.include_router(<group>_router, prefix="/api")`

6. **Add a test** in `tests/test_<group>.py`. Mirror an existing test file (e.g. `tests/test_scenarios.py`) for fixture usage.

## Steps for $1 $2

1. Determine the group from the path's first segment.
2. Open or create `backend/api/<group>.py`.
3. Add the handler with correct signature, Pydantic types, auth dependency.
4. If the file is new, wire it into `backend/main.py`.
5. Add a smoke test in `tests/test_<group>.py`.
6. Run `uv run pytest tests/test_<group>.py -v` and `uv run ruff check backend/`.
7. Report the route + example curl invocation.

If $1 isn't a valid HTTP method or $2 doesn't start with `/`, stop and ask for clarification.
