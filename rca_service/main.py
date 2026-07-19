"""Local RCA service — a runnable implementation of the RCA_agent (RCA
Intellect) HTTP contract the Knowledge Fabric binds to.

It serves the two GET endpoints the fabric's `rca_vision` / `rca_knowledge`
http data sources call, plus a C-scan image for the Visual tab:

  GET /api/image-analysis/{part_id}      -> ImageAnalysisOutput JSON (+ image_url)
  GET /api/rag/query?q=&collection=&top_k -> [{id,title,summary,score}]
  GET /api/cscan/{name}                  -> an SVG C-scan (defect image)

This stands in for a live RCA_agent deployment so the fabric's Defect /
PriorNCR / CAPARecommendation bindings resolve to real HTTP-sourced data.
Point the fabric at a real RCA_agent instead by changing the `base_url` of
the rca_vision / rca_knowledge sources in backend/data/sources.yaml.

Run:  .venv/bin/python rca_service/main.py     (defaults to 127.0.0.1:8000)
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

BASE = os.environ.get("RCA_SERVICE_BASE", "http://localhost:8000")

app = FastAPI(title="RCA Intellect (local service)")
# Images are loaded by <img> (no CORS needed), but allow all so a browser
# could also fetch the JSON directly during debugging.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# =============================================================================
# Vision — image analysis per part (RCA_agent's Image Analysis agent)
# =============================================================================
DEFECTS: dict[str, dict] = {
    "P-1234": {
        "id": "DEF-1234",
        "part_id": "P-1234",
        "defect_type": "delamination",
        "severity": "high",
        "location": "ply 7/8 interface, inboard bay 3",
        "candidate_causes": "insufficient consolidation pressure; autoclave regulator drift",
        "observations": "18 mm delamination at the ply 7/8 interface; C-scan amplitude drop of -14 dB over the affected region",
        "program": "Mirage",
        "cscan_db": "-14 dB",
        "image_url": f"{BASE}/api/cscan/P-1234.svg",
    },
    "P-3300": {
        "id": "DEF-3300",
        "part_id": "P-3300",
        "defect_type": "delamination",
        "severity": "medium",
        "location": "skin-to-doubler interface, station 220",
        "candidate_causes": "cure temperature undershoot; 1.8 mm ply gap at the doubler; vacuum loss during ramp",
        "observations": "9 mm delamination at the skin/doubler bondline; C-scan amplitude drop of -9 dB",
        "program": "Viper",
        "cscan_db": "-9 dB",
        "image_url": f"{BASE}/api/cscan/P-3300.svg",
    },
}


@app.get("/api/image-analysis/{part_id}")
def image_analysis(part_id: str):
    d = DEFECTS.get(part_id)
    if not d:
        return JSONResponse([], status_code=200)
    return d


# =============================================================================
# RAG — historical NCR + CAPA retrieval (RCA_agent's Qdrant knowledge base)
# =============================================================================
NCR_DOCS = [
    {"id": "NCR-2025-0417", "title": "NCR-2025-0417 · Delamination, ply 7/8, Mirage spar",
     "summary": "Post-cure C-scan flagged an 18mm delamination. Traced to autoclave pressure 12% below setpoint during the cure hold. Regulator found drifted out of calibration.",
     "score": 0.93},
    {"id": "NCR-2025-0188", "title": "NCR-2025-0188 · Vacuum-bag leak, bay 3",
     "summary": "Pre-cure bag-integrity check missed a 2 inHg/min leak; incomplete consolidation led to a ply-interface delamination.",
     "score": 0.81},
    {"id": "NCR-2024-0902", "title": "NCR-2024-0902 · Prepreg out-life exceeded",
     "summary": "Delamination after cure; prepreg had exceeded freezer out-life. Resin advanced, reduced tack and flow at the interface.",
     "score": 0.74},
    {"id": "NCR-2025-0331", "title": "NCR-2025-0331 · Resin viscosity out of spec",
     "summary": "Incoming resin batch viscosity 6% high; porosity and localized delamination on two panels.",
     "score": 0.63},
]

CAPA_DOCS = [
    {"id": "CAPA-2025-041", "title": "CAPA-2025-041 · Autoclave regulator PM + SPC alarm",
     "summary": "Replaced the autoclave pressure regulator; added a weekly regulator calibration check and an in-line cure-pressure SPC alarm. Effective — no recurrence in 9 months.",
     "score": 0.94},
    {"id": "CAPA-2025-017", "title": "CAPA-2025-017 · Dual-stage bag integrity check",
     "summary": "Introduced a dual-stage vacuum-bag integrity check before cure, with a documented hold-test. Leak escapes down ~80%.",
     "score": 0.79},
    {"id": "CAPA-2024-088", "title": "CAPA-2024-088 · Freezer out-life barcode gating",
     "summary": "Barcode scan gates prepreg at layup against freezer out-life. Partially effective — one recurrence, process retrained.",
     "score": 0.7},
]


@app.get("/api/rag/query")
def rag_query(q: str = "", collection: str = "ncr", top_k: int = 3):
    corpus = CAPA_DOCS if collection.lower().startswith("capa") else NCR_DOCS
    # Naive lexical relevance so `q` visibly matters; falls back to score order.
    terms = [t for t in q.lower().split() if len(t) > 3]

    def rel(doc: dict) -> float:
        text = (doc["title"] + " " + doc["summary"]).lower()
        hits = sum(1 for t in terms if t in text)
        return hits + doc.get("score", 0)

    ranked = sorted(corpus, key=rel, reverse=True)
    return ranked[: max(1, int(top_k))]


# =============================================================================
# C-scan image — a representative ultrasonic amplitude map with the defect
# =============================================================================
def _cscan_svg(part_id: str = "P-1234", loc: str = "ply 7/8", db: str = "-14 dB") -> str:
    return f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 300'>
  <defs>
    <linearGradient id='amp' x1='0' y1='0' x2='1' y2='0'>
      <stop offset='0' stop-color='#0b1e3f'/><stop offset='0.5' stop-color='#0e7c7b'/>
      <stop offset='0.8' stop-color='#e0b400'/><stop offset='1' stop-color='#c1121f'/>
    </linearGradient>
    <radialGradient id='defect' cx='50%' cy='50%' r='50%'>
      <stop offset='0' stop-color='#ff3b30'/><stop offset='0.45' stop-color='#ff9500'/>
      <stop offset='0.8' stop-color='#0e7c7b' stop-opacity='0.5'/>
      <stop offset='1' stop-color='#0b1e3f' stop-opacity='0'/>
    </radialGradient>
    <radialGradient id='noise' cx='50%' cy='50%' r='50%'>
      <stop offset='0' stop-color='#0e7c7b' stop-opacity='0.55'/>
      <stop offset='1' stop-color='#0b1e3f' stop-opacity='0'/>
    </radialGradient>
  </defs>
  <rect x='0' y='0' width='460' height='300' fill='#08152e'/>
  <!-- scan field -->
  <rect x='40' y='30' width='330' height='230' fill='#0b1e3f' stroke='#1b3358'/>
  <!-- low-amplitude background texture -->
  <ellipse cx='140' cy='110' rx='70' ry='48' fill='url(#noise)'/>
  <ellipse cx='250' cy='190' rx='90' ry='55' fill='url(#noise)'/>
  <ellipse cx='300' cy='90' rx='55' ry='40' fill='url(#noise)'/>
  <!-- grid -->
  <g stroke='#12294a' stroke-width='0.6'>
    <line x1='105' y1='30' x2='105' y2='260'/><line x1='170' y1='30' x2='170' y2='260'/>
    <line x1='235' y1='30' x2='235' y2='260'/><line x1='300' y1='30' x2='300' y2='260'/>
    <line x1='40' y1='87' x2='370' y2='87'/><line x1='40' y1='145' x2='370' y2='145'/>
    <line x1='40' y1='203' x2='370' y2='203'/>
  </g>
  <!-- delamination indication -->
  <ellipse cx='250' cy='150' rx='60' ry='34' fill='url(#defect)'/>
  <ellipse cx='250' cy='150' rx='60' ry='34' fill='none' stroke='#ffcc00' stroke-width='1' stroke-dasharray='4 3'/>
  <text x='250' y='205' fill='#ffd6d6' font-family='monospace' font-size='11' text-anchor='middle'>delamination {db}</text>
  <!-- axes -->
  <text x='205' y='278' fill='#7f97bd' font-family='monospace' font-size='10' text-anchor='middle'>scan X (mm)</text>
  <text x='16' y='150' fill='#7f97bd' font-family='monospace' font-size='10' text-anchor='middle' transform='rotate(-90 16 150)'>scan Y (mm)</text>
  <!-- amplitude legend -->
  <rect x='392' y='30' width='14' height='230' fill='url(#amp)' stroke='#1b3358'/>
  <text x='399' y='24' fill='#7f97bd' font-family='monospace' font-size='9' text-anchor='middle'>amp</text>
  <text x='420' y='36' fill='#7f97bd' font-family='monospace' font-size='9'>hi</text>
  <text x='420' y='258' fill='#7f97bd' font-family='monospace' font-size='9'>lo</text>
  <text x='40' y='20' fill='#cfe0ff' font-family='monospace' font-size='11'>C-scan · {part_id} · {loc}</text>
</svg>"""


@app.get("/api/cscan/{name}")
def cscan(name: str):
    part = name.split(".")[0]
    d = DEFECTS.get(part, {})
    loc = (d.get("location") or "ply 7/8").split(",")[0].strip()
    db = d.get("cscan_db", "-14 dB")
    return Response(content=_cscan_svg(part, loc, db), media_type="image/svg+xml")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "rca-intellect-local"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("RCA_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)
