# TCS Knowledge Fabric — Graph Data Snapshot

A self-contained, **fully synthetic** Neo4j graph used by the TCS Knowledge
Fabric demo. 43 nodes + ~52 relationships, hand-curated so the
supplier-onboarding, sanctions-proximity, alternative-supplier, tier-N
visibility, UBO disclosure and carrier-exposure scenarios all have
something interesting to traverse. No real OFAC entries, no real
companies — every name and identifier is made up.

The graph models the corporate + logistics neighbourhood around a single
fictional supplier (Hemlock Precision Castings, `SUP-001`):

- **20 Suppliers** with reliability scores, country, founded year
- **4 HoldingCompanies** sitting between suppliers and the rest of the world
- **5 SanctionedNetworkEntities** representing OFAC SDN listings
- **8 Carriers** (Maersk, MSC, Hapag-Lloyd, etc — real SCACs, synthetic stats)
- **3 Alliances** (2M, THE Alliance, Ocean Alliance)
- **3 PurchaseOrders + 3 Products** for backward-compat read scenarios

The fun edges:

| Relationship          | Edges | What it represents |
|---|---:|---|
| `PARENT_OF`           |  4 | Supplier → Supplier (corporate parent of) |
| `JOINT_VENTURE_WITH`  |  4 | Supplier ↔ Supplier (named JV, with share %) |
| `CONTROLLED_BY`       |  8 | Supplier → HoldingCompany (control %, since date) |
| `OWNS_SHARE`          |  5 | HoldingCompany → SanctionedNetworkEntity (pct, acquired) |
| `SOURCES_FROM`        |  8 | Supplier → Supplier (multi-tier supply chain, with material) |
| `SHIPS_VIA`           | 10 | Supplier → Carrier (preferred-carrier links with lane-share) |
| `MEMBER_OF`           |  7 | Carrier → Alliance |
| `PLACED` / `CONTAINS` |  6 | Supplier → PO → Product |

The centerpiece is the **Hemlock sanctions trail**: walking from `SUP-001`
two-to-three hops out reaches three different OFAC SDN entities through
holding-company chains. That's the killer query a flat table cannot do
efficiently — `MATCH p = shortestPath((s)-[*1..4]-(sdn:SanctionedNetworkEntity))`.

---

## File inventory

| File | What it does |
|---|---|
| `seed_neo4j.cypher` | The 91-statement seed script. Idempotent — starts with `MATCH (n) DETACH DELETE n;` so reapplying it always replaces the dataset cleanly. |
| `seed_neo4j.py`     | A small Python runner that opens a Bolt connection, splits the script on `;`, and applies each statement in its own transaction. Reads connection details from env vars. |
| `docker-compose.yml`| Spins up a local Neo4j 5 Community container exposing Bolt (7687) and the Neo4j Browser (7474). One-line start: `docker compose up -d`. |

---

## Quick start (3 minutes)

```bash
# 1. Spin up a local Neo4j
docker compose up -d

# 2. Wait ~10 seconds for it to be ready (the healthcheck reports STATUS=healthy)
docker compose ps

# 3. Install the Neo4j Python driver into any venv
python3 -m pip install --upgrade "neo4j>=5,<6"

# 4. Seed
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="passw0rd"
python3 seed_neo4j.py
```

The script prints `91 statements applied` plus a node-/relationship-count
summary at the end. If those counts match the inventory above, you're done.

To browse: open <http://localhost:7474>, sign in as `neo4j` / `passw0rd`,
and try one of the queries below.

---

## Sample queries to try

```cypher
// 1. The Hemlock sanctions trail — three SDN destinations within 4 hops.
MATCH path = shortestPath(
  (s:Supplier {supplier_id: 'SUP-001'})-[*1..4]-(sdn:SanctionedNetworkEntity)
)
RETURN sdn.name, length(path) AS hops,
       [n IN nodes(path) | coalesce(n.name, n.supplier_id, n.entity_id, n.holding_id)] AS chain
ORDER BY hops;

// 2. Carrier exposure on a newly-listed SDN — every carrier reachable
//    through a tainted supplier within 4 hops.
MATCH path = shortestPath(
  (sdn:SanctionedNetworkEntity {entity_id: 'SDN-NET-001'})-[*1..4]-(s:Supplier)
)
MATCH (s)-[:SHIPS_VIA]->(c:Carrier)-[:MEMBER_OF]->(a:Alliance)
RETURN DISTINCT c.name AS carrier, a.name AS alliance, s.name AS via_supplier
ORDER BY carrier;

// 3. Alternative suppliers for a blocked one — siblings via holding,
//    siblings via parent supplier, or JV partners.
MATCH (blocked:Supplier {supplier_id: 'SUP-013'})
MATCH (alt:Supplier) WHERE alt <> blocked
WITH blocked, alt,
  [(blocked)-[:CONTROLLED_BY]->(h:HoldingCompany)<-[:CONTROLLED_BY]-(alt) | h.name] AS via_holding,
  [(blocked)-[:JOINT_VENTURE_WITH]-(alt) | 'JV'] AS via_jv
WITH alt, via_holding + via_jv AS reasons
WHERE size(reasons) > 0
RETURN alt.supplier_id AS id, alt.name, reasons, alt.reliability_score;

// 4. Multi-tier supply chain for a product — walk SOURCES_FROM backwards
//    from the supplier that placed the PO.
MATCH (p:Product {product_id: 'P-EL-9001'})<-[:CONTAINS]-(:PurchaseOrder)<-[:PLACED]-(t1:Supplier)
OPTIONAL MATCH path = (t1)-[:SOURCES_FROM*0..3]->(tier_n:Supplier)
RETURN tier_n.supplier_id AS id, tier_n.name, length(path) + 1 AS tier
ORDER BY tier, id;
```

---

## Alternative setups

**No Docker?** Use [Neo4j Desktop](https://neo4j.com/download/) (free
GUI). Create a local DBMS, set the password to match `NEO4J_PASSWORD`
(or change the env var), then run `python3 seed_neo4j.py`.

**Want it in the cloud?** [Neo4j AuraDB Free](https://neo4j.com/cloud/aura-free/)
gives you a hosted instance. Point `NEO4J_URI` at the `neo4j+s://...`
URI Aura gives you and the rest works identically.

**Want to re-seed without dropping?** You can't — the script's first
statement is `MATCH (n) DETACH DELETE n`. If you've made manual edits in
the Browser you want to keep, export them with `apoc.export.cypher.all`
before re-running.

---

## Schema reference

```
(Supplier) -[:PARENT_OF]->          (Supplier)
(Supplier) -[:JOINT_VENTURE_WITH]-> (Supplier)         {share, since}
(Supplier) -[:CONTROLLED_BY]->      (HoldingCompany)   {pct, since}
(Supplier) -[:OWNS_SHARE]->         (SanctionedNetworkEntity)  {pct, acquired}
(Supplier) -[:SOURCES_FROM]->       (Supplier)         {material, since}
(Supplier) -[:SHIPS_VIA]->          (Carrier)          {primary, lane_share}
(Supplier) -[:PLACED]->             (PurchaseOrder)

(HoldingCompany) -[:OWNS_SHARE]->   (SanctionedNetworkEntity)  {pct, acquired}

(Carrier) -[:MEMBER_OF]->           (Alliance)         {since}

(PurchaseOrder) -[:CONTAINS]->      (Product)
```

Node properties live on each `CREATE` line of the seed file — open
`seed_neo4j.cypher` to see the full property list per label.
