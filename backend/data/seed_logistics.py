"""Generate the transactional logistics datasets.

Run from the repo root: `python backend/data/seed_logistics.py`.

Writes:
  Phase 1:
    - shipments.csv          (~3,000 rows, replacing the seed 30)
    - shipment_events.csv    (~19,000 rows, avg ~6 events per shipment)
  Phase 2:
    - customer_orders.csv    (~750 rows; covers ~25% of shipments — the rest
                              are internal/stock transfers without a named
                              customer order)
    - logistics.sqlite#bookings (~750 active bookings — proposed/tendered/
                              confirmed states; completed shipments archive)
  Phase 3:
    - logistics.sqlite#demurrage_charges (~250 rows; sparse, ~8% of
                              shipments trigger demurrage. Mix of accruing /
                              billed / disputed / waived / paid states with
                              prior_dispute_outcome populated for previously
                              decided rows so the autonomous-dispute scenario
                              has historical patterns to draw on.)

The script is deterministic: a fixed RNG seed plus sorted iteration means the
output is reproducible across runs. Re-run after editing distributions; commit
the resulting CSVs so reviewers don't have to re-generate.

Distribution model:
  - 70% ocean / 20% air / 10% rail-road, mode taken from the carrier
  - power-law shipment value ($100 - $250k, alpha ~ 1.8)
  - Pareto delay tail: 20% of lanes contribute 80% of variance
  - event sequences cluster around milestone_planned_at with realistic noise
  - ~15% of shipments carry an exception flag (delayed | customs_hold | damage)
  - Two seed shipments (S-700499, S-700412) are preserved verbatim so existing
    scenarios (SC-LN-STATUS-009, SC-LN-002) and any cached references keep
    working without modification.
"""
from __future__ import annotations

import csv
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

DATA_DIR = Path(__file__).resolve().parent
SHIPMENTS_CSV = DATA_DIR / "shipments.csv"
EVENTS_CSV = DATA_DIR / "shipment_events.csv"
CUSTOMER_ORDERS_CSV = DATA_DIR / "customer_orders.csv"
LOGISTICS_SQLITE = DATA_DIR / "logistics.sqlite"

SEED = 20260524        # date the script was first written; bumping changes everything
NUM_SHIPMENTS = 3000
AVG_EVENTS_PER_SHIPMENT = 4
EXCEPTION_PROB = 0.15
# Fraction of shipments tied to a named customer order (rest are internal /
# stock-transfer moves). Real enterprises hover around 20-30%.
CUSTOMER_ORDER_PROB = 0.25
# Booking statuses for ACTIVE bookings (completed shipments archive their
# booking and disappear from this table). Weighted toward "confirmed" because
# most active bookings have been accepted by the carrier.
BOOKING_STATUSES = (["proposed"] * 5) + (["tendered"] * 25) + (["confirmed"] * 70)
SLA_TIERS = (["premium"] * 25) + (["standard"] * 60) + (["economy"] * 15)
CUSTOMERS = [
    ("CUST-001", "Acme Industrial"),
    ("CUST-002", "Globex Manufacturing"),
    ("CUST-003", "Initech Holdings"),
    ("CUST-004", "Soylent Foods"),
    ("CUST-005", "Wayne Enterprises"),
    ("CUST-006", "Stark Industries"),
    ("CUST-007", "Cyberdyne Systems"),
    ("CUST-008", "Tyrell Corporation"),
    ("CUST-009", "Pied Piper Logistics"),
    ("CUST-010", "Hooli Hardware"),
    ("CUST-011", "Pearson Specialty Chemicals"),
    ("CUST-012", "Massive Dynamic"),
    ("CUST-013", "Umbrella Group"),
    ("CUST-014", "Vandelay Industries"),
    ("CUST-015", "Sirius Cybernetics"),
]

# Today as the "now" reference for ETA / event timestamps. Hard-coded so the
# generated dataset stays stable across runs even when the wall clock moves.
TODAY = datetime(2026, 5, 24, 12, 0, 0)

INCOTERMS = ["DDP", "DAP", "FOB", "CIF", "EXW", "DDU"]
HAZMAT_CLASSES = ["none", "none", "none", "none", "none", "none", "none", "3", "8", "9"]  # mostly none
PRIORITY_TIERS = ["standard", "standard", "standard", "premium", "premium", "economy"]
EXCEPTION_REASONS = ["delayed", "customs_hold", "damage", "vessel_change", "port_congestion"]

# Hand-written seed shipments preserved verbatim (used by existing scenarios).
SEED_SHIPMENTS: list[dict[str, str]] = [
    {
        "shipment_id": "S-700499", "customer_order": "ORD-44291", "sku": "P-EL-9001",
        "origin": "Singapore", "destination": "Rotterdam", "pallets": "8", "mode": "ocean",
        "vessel": "MV NORDIC CRYSTAL", "imo": "9876123", "current_position": "12 nm off Rotterdam",
        "eta": "2026-04-30T04:00Z", "port_code": "NLRTM", "port_congestion": "LOW",
        "berth_wait_days": "0.4", "carrier_id": "CR-MAEU", "lane_id": "L-SGSIN-NLRTM",
        "weight_kg": "12400", "volume_m3": "16.2", "value_usd": "184000", "incoterms": "DDP",
        "hazmat_class": "none", "priority_tier": "premium", "scheduled_eta": "2026-04-28T08:00Z",
        "variance_days": "2.0", "exception_flag": "delayed", "last_event_at": "2026-04-29T18:30Z",
    },
    {
        "shipment_id": "S-700412", "customer_order": "ORD-44218", "sku": "P-EL-9001",
        "origin": "Shanghai", "destination": "Hamburg", "pallets": "14", "mode": "ocean",
        "vessel": "MV PACIFIC SPIRIT", "imo": "9612345", "current_position": "East China Sea",
        "eta": "2026-04-28T18:00Z", "port_code": "DEHAM", "port_congestion": "HIGH",
        "berth_wait_days": "3.2", "carrier_id": "CR-MSCU", "lane_id": "L-CNSHA-DEHAM",
        "weight_kg": "21700", "volume_m3": "28.4", "value_usd": "312500", "incoterms": "DAP",
        "hazmat_class": "none", "priority_tier": "premium", "scheduled_eta": "2026-04-19T18:00Z",
        "variance_days": "9.0", "exception_flag": "delayed", "last_event_at": "2026-04-27T06:00Z",
    },
]


def _load_masters() -> tuple[list[dict], list[dict], list[dict]]:
    """Read the hand-written carriers/lanes/ports back so generated shipments
    only reference real ids."""
    def _read(name: str) -> list[dict]:
        with (DATA_DIR / name).open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    return _read("carriers.csv"), _read("lanes.csv"), _read("ports.csv")


def _sku_pool() -> list[str]:
    """SKUs taken from the existing products.csv plus a few logistics-flavoured
    extras so the dataset isn't dominated by 15 SKUs."""
    return [
        # Real products.csv ids — keep classifier-friendly
        "P-EL-9001", "P-EL-9002", "P-EL-9003",
        "P-CH-2210", "P-CH-2211",
        "P-MC-7100", "P-MC-7101", "P-MC-7102",
        "P-SW-3001", "P-SW-3002",
        "P-PK-4500", "P-PK-4501",
        "P-PW-1801", "P-PW-1802",
        "P-SN-5001",
        # Extras to broaden the distribution
        "P-EL-9101", "P-EL-9102", "P-CH-2230", "P-MC-7200", "P-PW-1850",
    ]


def _shipment_value_usd(rng: random.Random) -> float:
    """Draw shipment value in USD from a lognormal distribution.
    Tuned for enterprise freight: median ~ $3k, p90 ~ $30k, p99 ~ $200k.
    Capped at $250k so the dataset doesn't produce single mega-shipments
    that dominate every aggregate scenario."""
    return min(rng.lognormvariate(mu=8.0, sigma=1.8), 250_000)


def _generate_shipments(rng: random.Random) -> list[dict[str, str]]:
    carriers, lanes, ports = _load_masters()
    skus = _sku_pool()
    port_by_code = {p["port_code"]: p for p in ports}
    carriers_by_mode: dict[str, list[dict]] = {}
    for c in carriers:
        carriers_by_mode.setdefault(c["mode"], []).append(c)
    lanes_by_mode: dict[str, list[dict]] = {}
    for ln in lanes:
        lanes_by_mode.setdefault(ln["mode"], []).append(ln)

    # Mode mix: 70% ocean, 20% air, 10% rail-or-road.
    mode_pool = (["ocean"] * 70) + (["air"] * 20) + (["rail"] * 5) + (["road"] * 5)

    # Lanes flagged as "high variance" — 20% of lanes carry 80% of the delay weight.
    high_var_lanes = set(rng.sample(
        [ln["lane_id"] for ln in lanes],
        k=max(1, len(lanes) // 5),
    ))

    rows: list[dict[str, str]] = list(SEED_SHIPMENTS)
    seed_ids = {r["shipment_id"] for r in SEED_SHIPMENTS}

    # Numeric ids start above the seeds to avoid collisions.
    next_id = 700_600
    while len(rows) < NUM_SHIPMENTS:
        sid = f"S-{next_id}"
        next_id += 1
        if sid in seed_ids:
            continue

        mode = rng.choice(mode_pool)
        lane = rng.choice(lanes_by_mode.get(mode, lanes))
        # Carrier mode must match lane mode (within the master file)
        mode_carriers = carriers_by_mode.get(lane["mode"]) or carriers
        carrier = rng.choice(mode_carriers)

        origin_port = port_by_code.get(lane["origin_port"])
        dest_port = port_by_code.get(lane["destination_port"])
        origin_name = origin_port["name"] if origin_port else lane["origin_port"]
        dest_name = dest_port["name"] if dest_port else lane["destination_port"]

        transit_target = float(lane["transit_days_target"])
        # Pareto delay: high-variance lanes draw from a wider tail
        if lane["lane_id"] in high_var_lanes:
            delay = rng.gauss(2.5, 2.8)
        else:
            delay = rng.gauss(0.6, 1.2)
        delay = round(max(-2.0, min(delay, 18.0)), 1)

        # Schedule: pretend the shipment was tendered roughly transit + 5d ago.
        days_in_flight = rng.randint(2, int(transit_target) + 4)
        scheduled_eta = TODAY + timedelta(days=int(transit_target) - days_in_flight)
        actual_eta = scheduled_eta + timedelta(days=delay)

        # Exception flag
        is_exception = (rng.random() < EXCEPTION_PROB) or delay > 4
        exception_flag = rng.choice(EXCEPTION_REASONS) if is_exception else ""

        # Vessel: only meaningful for ocean; air uses flight number
        if lane["mode"] == "ocean":
            vessel = f"MV {rng.choice(['NORDIC', 'PACIFIC', 'ATLANTIC', 'ASIAN', 'BALTIC', 'ARCTIC', 'TROPIC', 'CALEDONIAN', 'IBERIAN', 'NIPPON'])} {rng.choice(['CRYSTAL', 'SPIRIT', 'GUARDIAN', 'STAR', 'EXPRESS', 'GLORY', 'PIONEER', 'BREEZE', 'TRADER', 'VICTORY'])}"
            imo = str(9_000_000 + rng.randint(100_000, 999_999))
        elif lane["mode"] == "air":
            vessel = f"{carrier['scac'][:2]}-CARGO-{rng.randint(100, 999)}"
            imo = "N/A"
        else:
            vessel = f"{carrier['name'][:6].upper()}-{rng.randint(1000, 9999)}"
            imo = "N/A"

        # Current position: rough text. For shipments still in transit pick from
        # the lane's origin/dest port + a generic mid-route phrase.
        positions = [
            f"off {origin_name}", f"approaching {dest_name}", "in transit",
            f"{dest_name} approach", f"{rng.randint(5, 200)} nm from {dest_name}",
        ]
        current_position = rng.choice(positions)
        port_code = dest_port["port_code"] if dest_port else lane["destination_port"]
        port_obj = port_by_code.get(port_code)
        port_congestion = port_obj["congestion_level"] if port_obj else "LOW"
        berth_wait = port_obj["berth_wait_p50_days"] if port_obj else "0.5"

        last_event = actual_eta - timedelta(hours=rng.randint(1, 72))

        rows.append({
            "shipment_id": sid,
            "customer_order": f"ORD-{rng.randint(44000, 49999)}",
            "sku": rng.choice(skus),
            "origin": origin_name,
            "destination": dest_name,
            "pallets": str(rng.randint(1, 36)),
            "mode": lane["mode"],
            "vessel": vessel,
            "imo": imo,
            "current_position": current_position,
            "eta": actual_eta.strftime("%Y-%m-%dT%H:%MZ"),
            "port_code": port_code,
            "port_congestion": port_congestion,
            "berth_wait_days": berth_wait,
            "carrier_id": carrier["carrier_id"],
            "lane_id": lane["lane_id"],
            "weight_kg": str(round(rng.uniform(50, 26000), 0)),
            "volume_m3": str(round(rng.uniform(0.2, 60), 1)),
            "value_usd": str(round(_shipment_value_usd(rng), 0)),
            "incoterms": rng.choice(INCOTERMS),
            "hazmat_class": rng.choice(HAZMAT_CLASSES),
            "priority_tier": rng.choice(PRIORITY_TIERS),
            "scheduled_eta": scheduled_eta.strftime("%Y-%m-%dT%H:%MZ"),
            "variance_days": str(delay),
            "exception_flag": exception_flag,
            "last_event_at": last_event.strftime("%Y-%m-%dT%H:%MZ"),
        })

    return rows


def _event_sequence_for(s: dict, rng: random.Random) -> Iterator[dict]:
    """Build a realistic milestone sequence for one shipment.

    Pattern: booked → picked_up → port_arrival → port_departure → in_transit
    → port_arrival (dest) → customs_cleared → delivered. Add a delay /
    customs_hold / vessel_change event if the shipment has an exception flag.
    """
    actual_eta = datetime.strptime(s["eta"], "%Y-%m-%dT%H:%MZ")
    scheduled_eta = datetime.strptime(s["scheduled_eta"], "%Y-%m-%dT%H:%MZ")
    variance_days = float(s["variance_days"])
    # The shipment lifecycle starts ~transit_days before scheduled_eta.
    transit_days = max(2, (actual_eta - scheduled_eta).days + 7)
    booked_at = scheduled_eta - timedelta(days=transit_days)

    sequence = [
        ("booked", booked_at, s["origin"]),
        ("picked_up", booked_at + timedelta(days=1), s["origin"]),
        ("port_departure", booked_at + timedelta(days=2), s["origin"]),
        ("in_transit", booked_at + timedelta(days=transit_days // 2), "mid-route"),
        ("port_arrival", actual_eta - timedelta(days=1), s["destination"]),
        ("customs_cleared", actual_eta, s["destination"]),
    ]
    # Final delivered event only for shipments whose ETA is in the past
    if actual_eta < TODAY:
        sequence.append(("delivered", actual_eta + timedelta(hours=rng.randint(4, 36)), s["destination"]))

    # Insert exception event for flagged shipments
    if s["exception_flag"]:
        insert_at = booked_at + timedelta(days=transit_days // 2 + rng.randint(-2, 2))
        sequence.insert(4, (s["exception_flag"], insert_at, "mid-route"))

    for idx, (event_type, when, location) in enumerate(sequence):
        # Each event's "planned" time = scheduled_eta-relative; "actual" = our timestamp.
        planned_offset = (when - booked_at).days
        planned = scheduled_eta - timedelta(days=transit_days - planned_offset)
        variance_hours = round((when - planned).total_seconds() / 3600, 1)
        yield {
            "event_id": f"E-{s['shipment_id']}-{idx + 1:02d}",
            "shipment_id": s["shipment_id"],
            "event_at": when.strftime("%Y-%m-%dT%H:%MZ"),
            "event_type": event_type,
            "location": location,
            "lat": "",   # synthetic lat/lon — leave empty rather than fabricate precise values
            "lon": "",
            "milestone_planned_at": planned.strftime("%Y-%m-%dT%H:%MZ"),
            "milestone_actual_at": when.strftime("%Y-%m-%dT%H:%MZ"),
            "variance_hours": str(variance_hours),
            "note": "" if event_type not in EXCEPTION_REASONS else f"Exception: {event_type.replace('_', ' ')} flagged ({variance_days}d variance)",
        }


def _write_csv(path: Path, rows: list[dict], headers: list[str]) -> None:
    # Pass `lineterminator="\n"` explicitly: csv.DictWriter defaults to "\r\n"
    # on every platform, which would write CRLF into files committed from
    # macOS/Linux and break readers that don't normalise newlines.
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


# =============================================================================
# Phase 2 generators
# =============================================================================
# Hand-pinned customer orders for the seed shipments — keeps SC-LN-002
# and SC-LN-STATUS-009 narratives intact (S-700412 → ORD-44218,
# S-700499 → ORD-44291). Generated orders fill in the rest.
SEED_CUSTOMER_ORDERS: list[dict[str, str]] = [
    {
        "order_id": "ORD-44291", "customer_id": "CUST-001", "customer_name": "Acme Industrial",
        "sku": "P-EL-9001", "qty": "120", "promised_delivery_date": "2026-04-30",
        "shipment_id": "S-700499", "sla_tier": "premium",
        "penalty_per_day_usd": "4200", "total_value_usd": "184000",
    },
    {
        "order_id": "ORD-44218", "customer_id": "CUST-005", "customer_name": "Wayne Enterprises",
        "sku": "P-EL-9001", "qty": "260", "promised_delivery_date": "2026-04-22",
        "shipment_id": "S-700412", "sla_tier": "premium",
        "penalty_per_day_usd": "12000", "total_value_usd": "312500",
    },
]


def _generate_customer_orders(
    shipments: list[dict], rng: random.Random
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = list(SEED_CUSTOMER_ORDERS)
    seed_shipments = {o["shipment_id"] for o in SEED_CUSTOMER_ORDERS}

    # Pick the subset of shipments that get a named customer order.
    eligible = [s for s in shipments if s["shipment_id"] not in seed_shipments]
    pool = rng.sample(eligible, k=int(len(shipments) * CUSTOMER_ORDER_PROB))

    next_seq = 50_000
    for s in pool:
        cust_id, cust_name = rng.choice(CUSTOMERS)
        tier = rng.choice(SLA_TIERS)
        # Premium SLAs carry meaningful penalties; economy is essentially zero.
        if tier == "premium":
            penalty = rng.randint(3000, 18000)
        elif tier == "standard":
            penalty = rng.randint(500, 3500)
        else:
            penalty = rng.randint(0, 400)
        # Total value loosely correlates with the shipment value.
        value = float(s["value_usd"])
        rows.append({
            "order_id": f"ORD-{next_seq}",
            "customer_id": cust_id,
            "customer_name": cust_name,
            "sku": s["sku"],
            "qty": str(rng.randint(20, 800)),
            "promised_delivery_date": s["scheduled_eta"][:10],
            "shipment_id": s["shipment_id"],
            "sla_tier": tier,
            "penalty_per_day_usd": str(penalty),
            "total_value_usd": str(round(value, 0)),
        })
        next_seq += 1
    return rows


# Hand-pinned bookings for the seed shipments. SC-LN-002 reads its booking
# off of S-700412 (and the rewired version triggers retender_booking against
# it), so the booking_id must be stable.
SEED_BOOKINGS: list[dict[str, str]] = [
    {
        "booking_id": "BK-700499-01", "shipment_id": "S-700499",
        "carrier_id": "CR-MAEU", "lane_id": "L-SGSIN-NLRTM", "mode": "ocean",
        "tendered_at": "2026-04-08T10:00Z",
        "base_cost_usd": "4100", "fuel_surcharge_usd": "615",
        "total_cost_usd": "4715", "status": "confirmed",
    },
    {
        "booking_id": "BK-700412-01", "shipment_id": "S-700412",
        "carrier_id": "CR-MSCU", "lane_id": "L-CNSHA-DEHAM", "mode": "ocean",
        "tendered_at": "2026-03-18T14:00Z",
        "base_cost_usd": "4200", "fuel_surcharge_usd": "630",
        "total_cost_usd": "4830", "status": "confirmed",
    },
]


def _generate_bookings(
    shipments: list[dict], rng: random.Random
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = list(SEED_BOOKINGS)
    seed_shipments = {b["shipment_id"] for b in SEED_BOOKINGS}

    # Active bookings only — only future-ETA shipments are eligible (past
    # ETAs would be `completed` and archived). Then sample down to ~750 to
    # match the plan's "active bookings only" sizing.
    eligible = [
        s for s in shipments
        if s["shipment_id"] not in seed_shipments
        and datetime.strptime(s["eta"], "%Y-%m-%dT%H:%MZ") >= TODAY
    ]
    target = max(0, 750 - len(SEED_BOOKINGS))
    selected = rng.sample(eligible, k=min(target, len(eligible)))
    next_seq = 100_000
    for s in selected:
        status = rng.choice(BOOKING_STATUSES)
        base = round(rng.uniform(800, 38000), 0)
        fuel = round(base * rng.uniform(0.10, 0.22), 0)
        total = base + fuel
        # Most bookings tendered a few days before scheduled departure.
        scheduled = datetime.strptime(s["scheduled_eta"], "%Y-%m-%dT%H:%MZ")
        lane_transit_estimate = max(2, int(float(s["variance_days"])))
        tendered = scheduled - timedelta(
            days=int(float(s["variance_days"])) + lane_transit_estimate + rng.randint(1, 7)
        )
        rows.append({
            "booking_id": f"BK-{next_seq}",
            "shipment_id": s["shipment_id"],
            "carrier_id": s["carrier_id"],
            "lane_id": s["lane_id"],
            "mode": s["mode"],
            "tendered_at": tendered.strftime("%Y-%m-%dT%H:%MZ"),
            "base_cost_usd": str(base),
            "fuel_surcharge_usd": str(fuel),
            "total_cost_usd": str(total),
            "status": status,
        })
        next_seq += 1
    return rows


_BOOKINGS_DDL = """
DROP TABLE IF EXISTS bookings;
CREATE TABLE bookings (
    booking_id          TEXT PRIMARY KEY,
    shipment_id         TEXT NOT NULL,
    carrier_id          TEXT NOT NULL,
    lane_id             TEXT NOT NULL,
    mode                TEXT NOT NULL,
    tendered_at         TEXT NOT NULL,
    base_cost_usd       REAL NOT NULL,
    fuel_surcharge_usd  REAL NOT NULL,
    total_cost_usd      REAL NOT NULL,
    status              TEXT NOT NULL
);
CREATE INDEX idx_bookings_shipment ON bookings(shipment_id);
CREATE INDEX idx_bookings_status   ON bookings(status);
"""

_DEMURRAGE_DDL = """
DROP TABLE IF EXISTS demurrage_charges;
CREATE TABLE demurrage_charges (
    charge_id             TEXT PRIMARY KEY,
    shipment_id           TEXT NOT NULL,
    port_code             TEXT NOT NULL,
    charge_type           TEXT NOT NULL,
    free_time_expired_at  TEXT NOT NULL,
    days_overage          REAL NOT NULL,
    daily_rate_usd        REAL NOT NULL,
    total_charge_usd      REAL NOT NULL,
    status                TEXT NOT NULL,
    responsible_party     TEXT NOT NULL,
    prior_dispute_outcome TEXT NOT NULL
);
CREATE INDEX idx_demurrage_shipment ON demurrage_charges(shipment_id);
CREATE INDEX idx_demurrage_status   ON demurrage_charges(status);
"""

# Hand-pinned demurrage charges so the dispute scenario has a stable case to
# reference. Targets the high-variance S-700412 (long delay → port stuck at
# Hamburg → demurrage accrues).
SEED_DEMURRAGE: list[dict[str, str]] = [
    {
        "charge_id": "DEM-S-700412-01", "shipment_id": "S-700412",
        "port_code": "DEHAM", "charge_type": "demurrage",
        "free_time_expired_at": "2026-04-21T08:00Z",
        "days_overage": "4.0", "daily_rate_usd": "1200",
        "total_charge_usd": "4800", "status": "billed",
        "responsible_party": "consignee", "prior_dispute_outcome": "n/a",
    },
]

# Charge-type weights — demurrage is most common, per_diem rare.
_DEMURRAGE_TYPE_POOL = (["demurrage"] * 55) + (["detention"] * 25) + (["storage"] * 15) + (["per_diem"] * 5)
# Status weights for fresh charges. Most are still accruing or billed; some
# already-decided ones (waived/paid) carry a prior_dispute_outcome so the
# autonomous-dispute scenario can find a "we've won similar before" pattern.
_DEMURRAGE_STATUS_POOL = (
    (["accruing"] * 35) + (["billed"] * 35) + (["disputed"] * 10)
    + (["waived"] * 10) + (["paid"] * 10)
)
_RESPONSIBLE_POOL = (["consignee"] * 50) + (["carrier"] * 30) + (["shipper"] * 20)


def _generate_demurrage(
    shipments: list[dict], rng: random.Random
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = list(SEED_DEMURRAGE)
    seed_charges = {r["shipment_id"] for r in SEED_DEMURRAGE}

    # Only ~8% of shipments accrue demurrage; bias toward shipments that
    # routed through HIGH-congestion ports (DEHAM, USLAX, CNTAO, INNSA) since
    # those are where free-time overruns are concentrated in real ops.
    high_friction_ports = {"DEHAM", "USLAX", "CNTAO", "INNSA"}
    high_friction = [s for s in shipments if s["port_code"] in high_friction_ports]
    other = [s for s in shipments if s["port_code"] not in high_friction_ports]
    # 70% of charges come from high-friction ports, 30% from elsewhere.
    target_total = 250 - len(SEED_DEMURRAGE)
    from_high = rng.sample(high_friction, k=min(int(target_total * 0.7), len(high_friction)))
    from_low = rng.sample(other, k=min(target_total - len(from_high), len(other)))
    selected = [s for s in (from_high + from_low) if s["shipment_id"] not in seed_charges]

    next_seq = 200_000
    for s in selected:
        ctype = rng.choice(_DEMURRAGE_TYPE_POOL)
        status = rng.choice(_DEMURRAGE_STATUS_POOL)
        # Daily rate varies by type; demurrage > detention > storage > per_diem.
        rate_map = {"demurrage": (800, 2200), "detention": (250, 600), "storage": (80, 250), "per_diem": (50, 150)}
        daily = round(rng.uniform(*rate_map[ctype]), 0)
        days = round(rng.uniform(1, 12), 1)
        total = round(daily * days, 0)
        # Free-time-expired timestamp = scheduled ETA + a few days of free
        # time, then overrun. Reuse shipment scheduled_eta as the anchor.
        sched = datetime.strptime(s["scheduled_eta"], "%Y-%m-%dT%H:%MZ")
        free_time_expired = sched + timedelta(days=rng.randint(3, 7))
        # waived / paid rows carry a historical outcome so the autonomous
        # dispute pattern has training data. accruing / billed / disputed
        # don't — those are the unresolved live charges.
        prior_outcome = (
            rng.choice(["won", "lost"]) if status in ("waived", "paid") else "n/a"
        )
        rows.append({
            "charge_id": f"DEM-{next_seq}",
            "shipment_id": s["shipment_id"],
            "port_code": s["port_code"],
            "charge_type": ctype,
            "free_time_expired_at": free_time_expired.strftime("%Y-%m-%dT%H:%MZ"),
            "days_overage": str(days),
            "daily_rate_usd": str(daily),
            "total_charge_usd": str(total),
            "status": status,
            "responsible_party": rng.choice(_RESPONSIBLE_POOL),
            "prior_dispute_outcome": prior_outcome,
        })
        next_seq += 1
    return rows


def _write_bookings_sqlite(rows: list[dict[str, str]]) -> None:
    """Replace logistics.sqlite.bookings with the freshly generated set.

    Idempotent: drops the table and re-creates.
    """
    LOGISTICS_SQLITE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOGISTICS_SQLITE)
    try:
        conn.executescript(_BOOKINGS_DDL)
        conn.executemany(
            "INSERT INTO bookings (booking_id, shipment_id, carrier_id, lane_id, "
            "mode, tendered_at, base_cost_usd, fuel_surcharge_usd, total_cost_usd, status) "
            "VALUES (:booking_id, :shipment_id, :carrier_id, :lane_id, :mode, "
            ":tendered_at, :base_cost_usd, :fuel_surcharge_usd, :total_cost_usd, :status)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _write_demurrage_sqlite(rows: list[dict[str, str]]) -> None:
    """Replace logistics.sqlite.demurrage_charges with the freshly generated set.

    Idempotent: drops the table and re-creates. Shares the file with bookings.
    """
    LOGISTICS_SQLITE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOGISTICS_SQLITE)
    try:
        conn.executescript(_DEMURRAGE_DDL)
        conn.executemany(
            "INSERT INTO demurrage_charges (charge_id, shipment_id, port_code, "
            "charge_type, free_time_expired_at, days_overage, daily_rate_usd, "
            "total_charge_usd, status, responsible_party, prior_dispute_outcome) "
            "VALUES (:charge_id, :shipment_id, :port_code, :charge_type, "
            ":free_time_expired_at, :days_overage, :daily_rate_usd, "
            ":total_charge_usd, :status, :responsible_party, :prior_dispute_outcome)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    rng = random.Random(SEED)
    shipments = _generate_shipments(rng)

    events: list[dict] = []
    for s in shipments:
        events.extend(_event_sequence_for(s, rng))

    orders = _generate_customer_orders(shipments, rng)
    bookings = _generate_bookings(shipments, rng)
    demurrage = _generate_demurrage(shipments, rng)

    shipment_headers = [
        "shipment_id", "customer_order", "sku", "origin", "destination", "pallets",
        "mode", "vessel", "imo", "current_position", "eta", "port_code",
        "port_congestion", "berth_wait_days", "carrier_id", "lane_id",
        "weight_kg", "volume_m3", "value_usd", "incoterms", "hazmat_class",
        "priority_tier", "scheduled_eta", "variance_days", "exception_flag",
        "last_event_at",
    ]
    event_headers = [
        "event_id", "shipment_id", "event_at", "event_type", "location",
        "lat", "lon", "milestone_planned_at", "milestone_actual_at",
        "variance_hours", "note",
    ]
    order_headers = [
        "order_id", "customer_id", "customer_name", "sku", "qty",
        "promised_delivery_date", "shipment_id", "sla_tier",
        "penalty_per_day_usd", "total_value_usd",
    ]

    _write_csv(SHIPMENTS_CSV, shipments, shipment_headers)
    _write_csv(EVENTS_CSV, events, event_headers)
    _write_csv(CUSTOMER_ORDERS_CSV, orders, order_headers)
    _write_bookings_sqlite(bookings)
    _write_demurrage_sqlite(demurrage)

    print(f"Wrote {len(shipments):,} shipments       → {SHIPMENTS_CSV}")
    print(f"Wrote {len(events):,} events          → {EVENTS_CSV}")
    print(f"Wrote {len(orders):,} customer_orders → {CUSTOMER_ORDERS_CSV}")
    print(f"Wrote {len(bookings):,} bookings        → {LOGISTICS_SQLITE} (bookings table)")
    print(f"Wrote {len(demurrage):,} demurrage       → {LOGISTICS_SQLITE} (demurrage_charges table)")


if __name__ == "__main__":
    main()
