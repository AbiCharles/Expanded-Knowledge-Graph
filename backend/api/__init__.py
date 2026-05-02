"""FastAPI router modules.

Each file in this package defines exactly one ``APIRouter``. ``main.py``
mounts them all under the ``/api`` prefix at app construction time:

  - ``auth`` — register / login / me / change-password
  - ``cases`` — case lifecycle + SSE event stream
  - ``decisions`` — reviewer decision sink + ticket queue
  - ``scenarios`` — catalog GET, custom save / edit / delete, autofill
  - ``datasources`` — registered data sources, query playground, upload
  - ``exports`` — CSV exports of cases + lineage
  - ``metrics`` — dashboard aggregates
"""
