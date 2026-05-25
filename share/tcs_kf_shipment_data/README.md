# TCS Knowledge Fabric — Shipping Data Snapshot

A self-contained, **fully synthetic** logistics mock dataset used by the TCS Knowledge Fabric
Knowledge Fabric demo. ~24,300 rows across 8 CSV files plus 2 SQLite tables,
totalling about 700 KB. No real customer names, no real OFAC entries, no PII —
everything is generated or hand-curated.

The data tells the story of a mid-size enterprise shipper: 3,000 active and
recently-completed shipments moving across 25 carriers, 40 lanes, 46 ports
(seaports + airports + rail terminals). 752 of those shipments fulfil a named
customer order (the rest are internal/stock transfers). 750 active bookings
sit in the SQLite store as the platform's write target. ~250 demurrage charges
overlay realistic financial exposure.

---

## File inventory

| File | Rows | Cols | What it holds |
|---|---:|---:|---|
| **shipments.csv**         | 3,000  | 26 | One row per shipment — origin/destination, vessel, current position, ETA, port, congestion, exception flag, weight/volume/value, incoterms, hazmat class, priority tier. The "operational" table. |
| **shipment_events.csv**   | 19,443 | 11 | Append-only milestone + exception event stream. Avg ~6 events per shipment (booked → picked_up → port_departure → in_transit → port_arrival → customs_cleared → delivered, plus exception inserts). Sorted by `event_at` gives the full trace. |
| **shipment_performance.csv** | 45  |  5 | Aggregated on-time-rate / late-count per SKU per quarter. Three quarters × 15 SKUs. Analytical, not operational. |
| **carriers.csv**          | 25     | 10 | Carrier master — Maersk, MSC, Hapag-Lloyd, CMA CGM, COSCO, FedEx, DHL, Lufthansa Cargo, etc. Real SCACs (Standard Carrier Alpha Codes); synthetic scorecard values. |
| **lanes.csv**             | 40     | 10 | Origin-destination corridors — Asia↔EU, Transpacific, Transatlantic, intra-EU, plus a few air + rail lanes. Captures target vs. p50/p95 transit days and current congestion. |
| **ports.csv**             | 46     | 10 | UN/LOCODE port master with synthetic operational state (congestion level, berth wait p50/p95, customs clearance time, labor / weather flags). Includes seaports (NLRTM, USLAX, CNSHA…), airports (DEFRA, USORD, LHRGB…), and rail terminals (DEDUS, PLLDZ). |
| **customer_orders.csv**   | 752    | 10 | Customer orders tied to shipments. Carries SLA tier (premium / standard / economy) and penalty $/day late — drives commercial decision scenarios. |
| **freight_rates.csv**     | 62     | 11 | Current contract + spot rate cards per (lane, carrier, container type). Mix of ocean / air / rail / road. |
| **logistics.sqlite#bookings** | 750 | 10 | Active carrier bookings (proposed / tendered / confirmed states; completed shipments archive their booking). The platform's write target for re-tender actions. |
| **logistics.sqlite#demurrage_charges** | 250 | 11 | Demurrage / detention / per-diem / storage charges. ~8% of shipments trigger one; biased toward HIGH-congestion ports (DEHAM, USLAX, CNTAO, INNSA). |

---

## How they relate (foreign keys)

```
shipments.shipment_id  ←─┬─  shipment_events.shipment_id   (1..*)
                         ├─  customer_orders.shipment_id   (0..1; ~25% of shipments)
                         ├─  bookings.shipment_id          (0..1 active)
                         └─  demurrage_charges.shipment_id (0..*)

shipments.carrier_id   ───  carriers.carrier_id            (1:1)
shipments.lane_id      ───  lanes.lane_id                  (1:1)
shipments.port_code    ───  ports.port_code                (1:1, destination port)

lanes.origin_port      ───  ports.port_code
lanes.destination_port ───  ports.port_code

freight_rates.lane_id    ─  lanes.lane_id
freight_rates.carrier_id ─  carriers.carrier_id

bookings.carrier_id      ─  carriers.carrier_id
bookings.lane_id         ─  lanes.lane_id

demurrage_charges.port_code ─ ports.port_code
```

All FK references are clean (verified — zero orphans).

---

## Column glossary (the non-obvious ones)

### shipments.csv
- `exception_flag` — one of `(blank)`, `delayed`, `customs_hold`, `damage`, `vessel_change`, `port_congestion`. ~15% of rows carry a flag; rows with delay > 4 days are also flagged.
- `priority_tier` — `standard` (50%), `premium` (34%), `economy` (16%). Influences how the agent treats the shipment in HITL scenarios.
- `variance_days` — actual ETA minus scheduled ETA. Positive = late, negative = early.
- `port_congestion` — LOW / MEDIUM / HIGH. Snapshot at the destination port. (Authoritative source is `ports.csv`; this is a denormalised mirror for fast filtering.)
- `value_usd` — drawn from a lognormal (median ~$3k, p99 capped at $250k). Enterprise freight mix.
- `imo` — vessel International Maritime Organization number for ocean shipments; "N/A" for air/rail/road.

### carriers.csv
- `scac` — real Standard Carrier Alpha Code (e.g. MAEU = Maersk).
- `on_time_rate_90d`, `damage_rate_90d` — synthetic but realistically distributed; air carriers cluster near 0.95, ocean carriers 0.85-0.94.
- `contract_renewal_date` — used in scenarios that surface upcoming renegotiations.

### lanes.csv
- `transit_days_p50`, `transit_days_p95` — distribution of actual transit times across historical shipments. `_target` is the carrier's commitment.
- `congestion_index` — 0-1 composite score; combines delay + port wait. >0.5 indicates a problematic lane.

### ports.csv
- `port_code` — real UN/LOCODE (5 chars, country + port).
- `berth_wait_p50_days`, `berth_wait_p95_days` — synthetic but plausible. NLRTM = 0.4d (clean), DEHAM = 3.2d (high friction).
- `labor_action_flag`, `weather_disruption_flag` — both `false` in this snapshot (no active disruptions).

### customer_orders.csv
- `sla_tier` — `premium` / `standard` / `economy`. Affects penalty exposure.
- `penalty_per_day_usd` — $/day late penalty. Premium tier: $3k-$18k; standard: $500-$3.5k; economy: $0-$400.

### bookings (SQLite)
- `status` — `proposed` (5%), `tendered` (27%), `confirmed` (68%). Completed shipments are archived (not in this table).
- `tendered_at` — ISO-8601 UTC timestamp.

### demurrage_charges (SQLite)
- `charge_type` — `demurrage` (52%), `detention` (26%), `storage` (17%), `per_diem` (5%).
- `status` — `accruing`, `billed`, `disputed`, `waived`, `paid`.
- `responsible_party` — `consignee` (most), `carrier`, or `shipper`.
- `prior_dispute_outcome` — `won`, `lost`, or `n/a`. Reflects the historical pattern on prior similar charges — used by an autonomous-dispute envelope. `n/a` for accruing/billed/disputed rows; populated for waived/paid.

---

## Suggested ways to use this data

### Pandas (1-liner per table)

```python
import pandas as pd, sqlite3
shipments = pd.read_csv("shipments.csv", parse_dates=["eta", "scheduled_eta", "last_event_at"])
events    = pd.read_csv("shipment_events.csv", parse_dates=["event_at", "milestone_planned_at", "milestone_actual_at"])
carriers  = pd.read_csv("carriers.csv", parse_dates=["contract_renewal_date"])
lanes     = pd.read_csv("lanes.csv")
ports     = pd.read_csv("ports.csv")
orders    = pd.read_csv("customer_orders.csv", parse_dates=["promised_delivery_date"])
rates     = pd.read_csv("freight_rates.csv", parse_dates=["valid_from", "valid_to"])

conn = sqlite3.connect("logistics.sqlite")
bookings  = pd.read_sql("SELECT * FROM bookings", conn)
demurrage = pd.read_sql("SELECT * FROM demurrage_charges", conn)
```

### SQL (load CSVs into the same SQLite file)

```sh
sqlite3 logistics.sqlite
sqlite> .mode csv
sqlite> .import shipments.csv shipments
sqlite> .import carriers.csv carriers
-- repeat for the rest
sqlite> SELECT carrier_id, COUNT(*) FROM shipments GROUP BY carrier_id ORDER BY 2 DESC;
```

### Quick interesting queries

```sql
-- Worst lanes by delay variance
SELECT lane_id, current_delay_days, congestion_index
FROM lanes ORDER BY current_delay_days DESC LIMIT 5;

-- Shipments at risk (exception flagged + premium customer)
SELECT s.shipment_id, s.origin, s.destination, s.exception_flag,
       o.customer_name, o.penalty_per_day_usd
FROM shipments s
LEFT JOIN customer_orders o ON o.shipment_id = s.shipment_id
WHERE s.exception_flag != '' AND o.sla_tier = 'premium'
ORDER BY o.penalty_per_day_usd DESC;

-- Demurrage exposure by port
SELECT port_code, COUNT(*) AS charges, SUM(total_charge_usd) AS exposure_usd
FROM demurrage_charges WHERE status IN ('accruing','billed')
GROUP BY port_code ORDER BY exposure_usd DESC;
```

---

## Provenance + reproducibility

- **Hand-written masters** (`carriers.csv`, `lanes.csv`, `ports.csv`, `freight_rates.csv`): curated for the demo. Real codes (SCACs, UN/LOCODEs), synthetic operational state.
- **Generated transactional** (`shipments.csv`, `shipment_events.csv`, `customer_orders.csv`, `bookings`, `demurrage_charges`): produced deterministically by `backend/data/seed_logistics.py` with `SEED=20260524`. Re-running the script with the same seed produces byte-identical CSVs.
- Distribution model documented inline in the seed script: 70% ocean / 20% air / 10% rail-road, lognormal shipment value, Pareto delay tail, ~15% exception rate.

---

## What this is *not*

- Not based on any real customer data
- Not anonymised production data — fully synthetic
- Not a benchmark dataset — the numbers are plausible but not statistically validated against a real shipper's distribution
- Not suitable for training models you'd deploy against real-world freight (the noise / correlations are seeded, not learned)

---

## Questions / changes

Reach out to whoever sent you this zip. The source seed script + ontology + scenario layer all live in the parent TCS Knowledge Fabric project.

— Snapshot generated 2026-05-25 from commit `4916376` of github.com/AbiCharles/Expanded-Knowledge-Graph
