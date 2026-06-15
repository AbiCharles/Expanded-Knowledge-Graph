#!/usr/bin/env python3
"""Generate docs/datasets-and-rules.pptx — domain-expert reference deck.

9 slides, formatted to match docs/KF_Framework_Comparison_glossary.pptx:
  - TCS logo + tagline (top-left)
  - Section label (top-centre, small caps grey)
  - "KNOWLEDGE FABRIC · CONFIDENTIAL · NN / 09" (top-right, crimson)
  - Title in Georgia 29pt bold navy + subtitle in Georgia 13pt grey
  - Dense 4-column tables with dark navy headers
  - Copyright footer at the bottom

Audience: procurement / logistics SMEs. Business-first language; no
JSON / YAML / SQL.

Re-runnable: regenerates the file in-place. Scenario titles + flags
are read from backend/scenarios/*.yaml so the deck doesn't drift from
the live catalogue.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt


REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "docs" / "datasets-and-rules.pptx"
SCENARIOS_DIR = REPO_ROOT / "backend" / "scenarios"

# Brand palette — exactly the values used by KF_Framework_Comparison_glossary.
NAVY = RGBColor(0x1E, 0x27, 0x61)        # titles, headers, table heads
NAVY_LIGHT = RGBColor(0x9F, 0xB0, 0xD8)  # verdict stripe, callouts
CRIMSON = RGBColor(0x9B, 0x22, 0x26)     # confidential label
GREEN = RGBColor(0x2C, 0x6E, 0x49)       # AHEAD / COMPARABLE
AMBER = RGBColor(0xB8, 0x86, 0x0B)       # PARTIAL
GREY_DARK = RGBColor(0x5A, 0x5A, 0x5A)   # body text
GREY_MED = RGBColor(0x64, 0x70, 0x8A)    # secondary text
GREY_LIGHT = RGBColor(0x8A, 0x8F, 0xA0)  # captions, chrome
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TABLE_ALT = RGBColor(0xF6, 0xF6, 0xF6)   # subtle alt-row tint

TOTAL_SLIDES = 9


# =============================================================================
# Low-level drawing helpers
# =============================================================================
def _set_run(run, *, size: float, font: str = "Arial",
             color=GREY_DARK, bold: bool = False) -> None:
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def _add_text(slide, left: float, top: float, width: float, height: float,
              text: str, *, size: float, font: str = "Arial",
              color=GREY_DARK, bold: bool = False,
              align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height),
    )
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_bottom = Inches(0)
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    _set_run(run, size=size, font=font, color=color, bold=bold)
    return tf


def _add_rect(slide, left: float, top: float, width: float, height: float,
              fill_color=NAVY, line: bool = False):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left), Inches(top), Inches(width), Inches(height),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if not line:
        shape.line.fill.background()
    return shape


# =============================================================================
# Page chrome — applied identically to every slide
# =============================================================================
def _draw_chrome(slide, page_num: int, section_label: str) -> None:
    # Top-left: TCS logo + tagline.
    _add_text(slide, 0.5, 0.3, 1.5, 0.4, "TCS",
              size=22, bold=True, color=NAVY)
    _add_text(slide, 0.5, 0.65, 2.5, 0.25, "Tata Consultancy Services",
              size=7.5, color=GREY_LIGHT)

    # Top-centre: section label, small caps grey.
    _add_text(slide, 3.2, 0.34, 6.5, 0.3, section_label.upper(),
              size=9, bold=True, color=GREY_LIGHT,
              align=PP_ALIGN.CENTER)

    # Top-right: confidential / page count.
    pages = f"KNOWLEDGE FABRIC · CONFIDENTIAL · {page_num:02d} / {TOTAL_SLIDES:02d}"
    _add_text(slide, 9.5, 0.34, 3.5, 0.3, pages,
              size=9, bold=True, color=CRIMSON,
              align=PP_ALIGN.RIGHT)

    # Thin separator under the chrome.
    _add_rect(slide, 0.5, 0.92, 12.33, 0.012, fill_color=GREY_LIGHT)

    # Bottom footer.
    _add_text(
        slide, 0.5, 7.15, 12.33, 0.25,
        "© 2026 Tata Consultancy Services Limited. All rights reserved. · TCS Confidential",
        size=8, color=GREY_LIGHT, align=PP_ALIGN.CENTER,
    )


def _draw_title(slide, title: str, subtitle: str) -> None:
    _add_text(slide, 0.5, 1.1, 12.3, 0.85, title,
              size=29, font="Georgia", bold=True, color=NAVY)
    _add_text(slide, 0.5, 2.0, 12.3, 0.55, subtitle,
              size=13, font="Georgia", color=GREY_DARK)


# =============================================================================
# Generic 4-column table — the workhorse format of the source deck
# =============================================================================
def _draw_table(
    slide,
    *,
    top: float,
    cols: list[tuple[str, float]],   # (header text, width-in-inches)
    rows: list[list[str]],
    cell_size_body: float = 8.5,
    cell_size_header: float = 8.5,
    row_height: float = 0.55,
    first_col_bold_navy: bool = True,
    last_col_bold: bool = False,
    last_col_color=GREEN,
) -> None:
    """Draws a header strip + data rows. First column is the row label.
    Optional last-column accent (e.g. COMPARABLE / AHEAD in green)."""
    left = 0.5
    # Header strip — navy bar, white bold text.
    _add_rect(slide, left, top, sum(w for _, w in cols), 0.35, fill_color=NAVY)
    x = left
    for header, width in cols:
        _add_text(
            slide, x + 0.10, top + 0.05, width - 0.20, 0.28, header.upper(),
            size=cell_size_header, bold=True, color=WHITE,
            anchor=MSO_ANCHOR.MIDDLE,
        )
        x += width

    # Rows.
    row_top = top + 0.35
    for row_idx, row in enumerate(rows):
        # Alternating tint.
        if row_idx % 2 == 1:
            _add_rect(slide, left, row_top,
                      sum(w for _, w in cols), row_height,
                      fill_color=TABLE_ALT)
        x = left
        for col_idx, (header, width) in enumerate(cols):
            value = row[col_idx] if col_idx < len(row) else ""
            is_first = col_idx == 0
            is_last = col_idx == len(cols) - 1
            color = NAVY if (is_first and first_col_bold_navy) else GREY_DARK
            bold = is_first and first_col_bold_navy
            if is_last and last_col_bold:
                color = last_col_color
                bold = True
            _add_text(
                slide, x + 0.10, row_top + 0.06, width - 0.20, row_height - 0.12,
                value, size=cell_size_body, color=color, bold=bold,
                anchor=MSO_ANCHOR.MIDDLE,
            )
            x += width
        # Cell bottom border (thin grey).
        _add_rect(slide, left, row_top + row_height - 0.005,
                  sum(w for _, w in cols), 0.005, fill_color=GREY_LIGHT)
        row_top += row_height


# =============================================================================
# Scenario inventory (read from disk so the deck stays current)
# =============================================================================
def _load_scenarios() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "id" in data:
            out[data["id"]] = data
    return out


# =============================================================================
# Slides
# =============================================================================
def slide_01_title(prs: Presentation) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 1, "Datasets & rules · reference for domain experts")
    _draw_title(
        s,
        "The data and rules behind the agent",
        "Reference for procurement and logistics domain experts. "
        "What the agent reads, what it understands, what it does.",
    )

    # Three-pane summary.
    cols = [
        ("Pillar", 4.0),
        ("What it is", 4.5),
        ("Where to verify", 4.0),
    ]
    rows = [
        ["Data sources",
         "Every fact on a case card started as a row in one of 14 sources.",
         "Section A · slide 02"],
        ["Ontology",
         "The dictionary of concepts the agent understands (Supplier, Carrier, "
         "SanctionsProximity).",
         "Section B · slide 03"],
        ["Scenarios",
         "Named recipes — one per kind of work — the agent can perform.",
         "Section C · slides 04 – 06"],
        ["Rules",
         "Guardrails on when the agent acts alone, when a human is asked, "
         "what stays immutable.",
         "Section D · slide 07"],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.85)

    # Bottom callout — what feedback is most valuable.
    _add_rect(s, 0.5, 6.55, 12.33, 0.4, fill_color=NAVY)
    _add_text(
        s, 0.65, 6.6, 12.0, 0.3,
        "WHAT WE NEED FROM YOU:  flag anything in this deck that doesn't match how your team actually works.",
        size=10, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE,
    )


def slide_02_data_sources(prs: Presentation) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 2, "Section A · the data sources behind every fact card")
    _draw_title(
        s,
        "Data sources — 14 sources, four kinds",
        "If a fact is wrong on a case, the row behind it is wrong in one of these sources. "
        "All can be edited by SMEs.",
    )

    cols = [
        ("Kind", 1.7),
        ("Examples", 4.3),
        ("What's in it / who owns it", 4.5),
        ("Backs (ontology)", 1.83),
    ]
    rows = [
        ["Spreadsheets (CSV)",
         "products, sanctions, carriers, lanes, ports, freight_rates, customer_orders",
         "Hand-curated master data. ~5,000 rows. Procurement + logistics SMEs maintain.",
         "Product, Carrier, Lane, Port, FreightRate"],
        ["Activity feeds (CSV)",
         "shipments, shipment_events, shipment_performance",
         "Synthetic stand-in for a live tracking feed. ~22k rows; mirrors what an OMS would push.",
         "Shipment, ShipmentEvent"],
        ["Operational stores (SQLite)",
         "logistics.sqlite, governance.sqlite",
         "Write targets. Bookings + demurrage charges; prior reviewer decisions. The agent writes here.",
         "Booking, PriorOverride"],
        ["Policy library (vector)",
         "policy_corpus (5 SOP markdown excerpts)",
         "Semantic search over policy text. Returns the most-relevant excerpts to a question.",
         "PolicyExcerpt"],
        ["Knowledge graph (Neo4j)",
         "supplier networks, alliances, sanctions ownership chains",
         "Relationships. Powers the 3-hop sanctions walk, UBO disclosure, carrier alliance reach.",
         "Supplier, SanctionsProximity, UltimateBeneficialOwner"],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.78,
                cell_size_body=8.0)


def slide_03_ontology(prs: Presentation) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 3, "Section B · the vocabulary the agent uses")
    _draw_title(
        s,
        "Ontology — concepts, in four families",
        "Every fact card has a class label (e.g. SanctionsProximity). The ontology is the dictionary "
        "that defines them. 27 classes across four families.",
    )

    cols = [
        ("Family", 2.0),
        ("Concepts (classes)", 5.0),
        ("Where its data comes from", 3.3),
        ("Used by", 2.03),
    ]
    rows = [
        ["tcs_core",
         "Product, SanctionedEntity, PriorOverride, PolicyExcerpt",
         "Products CSV, sanctions CSV, governance SQLite, policy corpus",
         "Every HITL scenario"],
        ["supply_chain",
         "Supplier, PurchaseOrder, SanctionsProximity, UltimateBeneficialOwner, CarrierExposure, TierSupplier, AlternativeSupplier",
         "Mostly Neo4j graph; some CSV",
         "All SC-PP-* scenarios"],
        ["logistics",
         "Shipment, ShipmentEvent, Carrier, Lane, Port, Booking, FreightRate, CustomerOrder, DemurrageCharge",
         "Carriers / lanes / ports CSVs; logistics SQLite",
         "All SC-LN-* scenarios"],
        ["supply_chain_demo",
         "Product, PriorOverride (demo-only variants)",
         "Demo-seeded CSVs",
         "Sandbox + demo cases"],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=1.0,
                cell_size_body=8.0)

    # Bottom note.
    _add_text(
        s, 0.5, 6.6, 12.3, 0.4,
        "Ontology change vs data change: a missing CONCEPT (e.g. \"we also care about beneficial owners' citizenship\") "
        "is an ontology edit. A missing ROW is a data edit. Different fix paths.",
        size=9, color=GREY_MED,
    )


def slide_04_scenarios_overview(prs: Presentation) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 4, "Section C · 28 scenarios across four domains")
    _draw_title(
        s,
        "Scenarios at a glance",
        "Each scenario is a named recipe. Triggered by operator prompt phrases (match_keywords), "
        "executes a fixed evidence-gathering flow, and either routes to a reviewer (HITL) or "
        "applies a guardrail (autonomous).",
    )

    cols = [
        ("Domain", 2.2),
        ("Count", 1.0),
        ("Examples", 6.0),
        ("HITL / Autonomous", 3.13),
    ]
    rows = [
        ["Procurement (SC-PP-*)", "7",
         "Supplier onboarding (SC-PP-008), UBO ownership walk (SC-PP-UBO-023), carrier-exposure containment (SC-PP-CARRIER-EXP-022)",
         "6 HITL, 1 autonomous"],
        ["Logistics (SC-LN-*)", "11",
         "Mode-switch ocean→air (SC-LN-002), port disruption reroute (SC-LN-PORT-DISRUPTION-020), demurrage auto-dispute (SC-LN-DEMURRAGE-AUTO-025)",
         "5 HITL, 6 autonomous"],
        ["Trade compliance (SC-TC-*)", "2",
         "Override on sanctioned counterparty (SC-TC-007), encryption-module SDN hit (SC-TC-008)",
         "Both HITL"],
        ["Self-service lookups (SC-ONTO-*)", "8",
         "Auto-generated, one per ontology class: \"look up Product / Supplier / SanctionedEntity\"",
         "All autonomous"],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.95,
                cell_size_body=8.0, last_col_bold=True, last_col_color=NAVY)


def slide_05_pp_spotlight(prs: Presentation, scenarios: dict) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 5, "Section C · spotlight · procurement")
    _draw_title(
        s,
        "Spotlight — supplier onboarding (SC-PP-008)",
        "The canonical demo case. Five data sources fused in one review. Procurement lead decides "
        "with the full evidence package on the audit trail.",
    )

    cols = [
        ("What", 2.5),
        ("Detail", 9.8),
    ]
    rows = [
        ["Triggered by",
         "Operator types phrases like \"onboard with graph,\" \"multi-source onboarding,\" "
         "\"sanctions proximity,\" \"hemlock onboarding.\""],
        ["What the agent gathers",
         "(1) The supplier's corporate network from the graph. (2) Their products from the CSV. "
         "(3) Live OFAC SDN matches. (4) Prior onboarding decisions on similar suppliers. "
         "(5) Relevant ESG / SOP excerpts via semantic search."],
        ["Decision shape",
         "HITL. Procurement lead approves, rejects, or requests more info. Three canned reject reasons: "
         "sanctions proximity too close, carrier-alliance concentration, reliability below tier-1 threshold."],
        ["What happens on approve",
         "Supplier enters the active tier-1 pool. Evidence package is captured on the audit trail."],
        ["What happens on reject",
         "Supplier is NOT added. Reason is recorded. Future similar candidates will see this case via PriorOverride."],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.82,
                cell_size_body=8.5)


def slide_06_ln_spotlight(prs: Presentation, scenarios: dict) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 6, "Section C · spotlight · logistics")
    _draw_title(
        s,
        "Spotlight — mode switch + autonomous demurrage",
        "Two logistics scenarios, both real demos. One is HITL with a high-stakes trade-off; "
        "the other is fully autonomous within a tight guardrail.",
    )

    cols = [
        ("Scenario", 3.0),
        ("What it does", 5.3),
        ("Trade-off / guardrail", 4.0),
    ]
    rows = [
        ["SC-LN-002 — Mode-switch ocean → air",
         "A shipment is behind schedule. The agent presents the option to switch from ocean (MSC) to "
         "air (Lufthansa Cargo) on a critical lane.",
         "18% cost uplift to recover 11 schedule days. Planner approves or rejects."],
        ["SC-LN-PORT-DISRUPTION-020 — Port reroute",
         "A port closes or congests. The agent walks every shipment touching the lane and proposes "
         "per-shipment actions.",
         "HITL. Planner sees all affected shipments together."],
        ["SC-LN-DEMURRAGE-AUTO-025 — Auto-dispute",
         "Small demurrage charges with a prior-win precedent are disputed automatically.",
         "ENVELOPE: charge ≤ $500 + at least one prior win. Above the envelope, routes to HITL."],
        ["SC-LN-SLA-RISK-022 — SLA risk",
         "A shipment is at risk of breaching the customer SLA penalty window.",
         "Expedite at extra cost or accept the penalty. Planner decides."],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.92,
                cell_size_body=8.5)


def slide_07_rules(prs: Presentation) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 7, "Section D · the guardrails and the audit trail")
    _draw_title(
        s,
        "Rules — when the agent acts, when it learns",
        "Four pillars: when work can complete without a human; when the platform learns from "
        "reviewer behaviour; what stays immutable; and who can do what.",
    )

    cols = [
        ("Rule", 2.5),
        ("How it works", 6.3),
        ("Why it matters", 3.5),
    ]
    rows = [
        ["Autonomous envelopes",
         "Each autonomous scenario carries a guardrail (e.g. \"demurrage charge ≤ $500 + at least one prior win\"). "
         "If the guardrail fails, the case routes to HITL automatically.",
         "The agent acts alone only inside narrow, signed-off limits."],
        ["Promoted patterns (compounding loop)",
         "Reviewers flag 1–3 load-bearing facts per decision. When the same driver shows up in many similar "
         "decisions, an admin can promote it. Future matching cases see an advisory chip.",
         "The platform learns from real reviewer behaviour. Reversible."],
        ["Immutable audit trail",
         "Every case is pinned to the scenario version it ran against. Lineage is append-only. "
         "Scenario edits create a new version; the old version stays inspectable forever.",
         "Auditors can answer \"what spec was running when?\" without git archaeology."],
        ["Access control",
         "Operators submit cases. Reviewers (named per scenario) decide on them. Admins edit scenarios "
         "and promote patterns. Every state change is tied to a username.",
         "Roles are enforced at the API; UI hides what the role can't access."],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.95,
                cell_size_body=8.5)


def slide_08_glossary(prs: Presentation) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 8, "Section E · plain-English definitions")
    _draw_title(
        s,
        "Glossary — words used in this deck",
        "Short definitions for the terms the system uses. Useful as a back-of-the-room reference "
        "during a walkthrough.",
    )

    cols = [
        ("Term", 2.4),
        ("What it means", 6.0),
        ("In our system", 3.93),
    ]
    rows = [
        ["Case",
         "One operator-initiated unit of work.",
         "Has a prompt, a scenario, evidence, eventually a decision."],
        ["Scenario",
         "A named recipe for how the agent should handle a kind of work.",
         "Versioned. Triggered by match_keywords. ~28 today."],
        ["Ontology",
         "The dictionary of concepts the system understands.",
         "Defines classes (Supplier, Carrier, etc.) and their fields."],
        ["Data source",
         "Where rows of data live.",
         "14 sources today: CSVs, SQLites, graph, vector store, HTTP."],
        ["Lineage",
         "The immutable record of every step the agent took during a case.",
         "Append-only audit trail."],
        ["Scenario version",
         "Every edit produces a new immutable snapshot.",
         "Old versions stay forever (Phase 1)."],
        ["Load-bearing fact",
         "An evidence card the reviewer flagged as having tipped the decision.",
         "1–3 per case (Phase 2)."],
        ["Promoted pattern",
         "A recurring driver across many decisions, promoted by an admin into the scenario.",
         "Surfaces as an advisory chip on future matching cases (Phase 3b)."],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.5,
                cell_size_body=8.5)


def slide_09_closing(prs: Presentation) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(s, 9, "The feedback we want from domain experts")
    _draw_title(
        s,
        "Where domain expertise tips the balance",
        "We can keep the platform self-consistent. We can't tell you whether it matches the way your "
        "team actually works. That's the highest-value review you can give us.",
    )

    cols = [
        ("If you find…", 4.5),
        ("…it likely means…", 4.0),
        ("…and the fix is", 3.83),
    ]
    rows = [
        ["A dataset is missing a column or row your team cares about",
         "Data source is incomplete",
         "Update the CSV / SQLite; reload"],
        ["A scenario doesn't capture how you actually decide",
         "The recipe needs a step or a rationale option",
         "Scenario edit (bumps version)"],
        ["A concept is missing (\"we also care about X\")",
         "Ontology is incomplete",
         "Ontology edit (engineering pair-up)"],
        ["A rule fires too aggressively or not enough",
         "Guardrail / envelope is mis-tuned",
         "Adjust the envelope (admin)"],
        ["A promoted pattern doesn't match your experience",
         "The platform learned from a small or biased sample",
         "Demote it (audit trail keeps the record)"],
    ]
    _draw_table(s, top=2.85, cols=cols, rows=rows, row_height=0.7,
                cell_size_body=8.5)

    # Final callout bar.
    _add_rect(s, 0.5, 6.5, 12.33, 0.5, fill_color=NAVY)
    _add_text(
        s, 0.65, 6.55, 12.0, 0.4,
        "MARK THIS DECK UP.  Send it back with notes.  Every gap you find becomes a scenario edit, a data fix, or an ontology revision.",
        size=11, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE,
        align=PP_ALIGN.CENTER,
    )


# =============================================================================
# Build
# =============================================================================
def build() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    scenarios = _load_scenarios()

    slide_01_title(prs)
    slide_02_data_sources(prs)
    slide_03_ontology(prs)
    slide_04_scenarios_overview(prs)
    slide_05_pp_spotlight(prs, scenarios)
    slide_06_ln_spotlight(prs, scenarios)
    slide_07_rules(prs)
    slide_08_glossary(prs)
    slide_09_closing(prs)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT_PATH)
    return OUT_PATH


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
