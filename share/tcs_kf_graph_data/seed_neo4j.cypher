// =============================================================================
// TCS Knowledge Fabric — Neo4j supply-chain demo seed
// =============================================================================
// 20 suppliers + 5 sanctioned-network entities + 8 carriers + 3 ocean alliances
// plus the relationships that make a graph more useful than a flat table:
// parent/subsidiary chains, joint ventures, ownership stakes, shipping
// preferences, alliance membership, and (critically) the indirect-ownership
// trail that puts certain suppliers within 2 hops of an OFAC-listed shell.
//
// Centerpiece: "Hemlock Precision Castings" — the procurement-onboarding
// case study. The agent traversing from Hemlock reaches "Shengli Shell
// Trading" (sanctioned) in two hops via the parent holding company.
//
// Run from the repo root:
//   source .venv/bin/activate
//   python3 backend/data/seed_neo4j.py
//
// Idempotent: drops all nodes/relationships before re-creating.
// =============================================================================

// ---- Clean slate -----------------------------------------------------------
MATCH (n) DETACH DELETE n;

// ---- Suppliers (20) --------------------------------------------------------
CREATE (:Supplier {supplier_id: 'SUP-001', name: 'Hemlock Precision Castings', country: 'US', reliability_score: 0.88, founded_year: 1987, employees: 480});
CREATE (:Supplier {supplier_id: 'SUP-002', name: 'Apex Metalworks',            country: 'US', reliability_score: 0.91, founded_year: 1962, employees: 2100});
CREATE (:Supplier {supplier_id: 'SUP-003', name: 'Granite Forging Co',         country: 'US', reliability_score: 0.86, founded_year: 1974, employees: 360});
CREATE (:Supplier {supplier_id: 'SUP-004', name: 'Beacon Chemicals',           country: 'US', reliability_score: 0.93, founded_year: 1955, employees: 1750});
CREATE (:Supplier {supplier_id: 'SUP-005', name: 'Vanguard Composites',        country: 'US', reliability_score: 0.89, founded_year: 1991, employees: 540});
CREATE (:Supplier {supplier_id: 'SUP-006', name: 'Crestfall Industries',       country: 'GB', reliability_score: 0.92, founded_year: 1948, employees: 3200});
CREATE (:Supplier {supplier_id: 'SUP-007', name: 'Trident Castings',           country: 'GB', reliability_score: 0.84, founded_year: 1969, employees: 290});
CREATE (:Supplier {supplier_id: 'SUP-008', name: 'Meridian Polymers',          country: 'DE', reliability_score: 0.90, founded_year: 1981, employees: 720});
CREATE (:Supplier {supplier_id: 'SUP-009', name: 'Onyx Steel Works',           country: 'DE', reliability_score: 0.87, founded_year: 1923, employees: 4100});
CREATE (:Supplier {supplier_id: 'SUP-010', name: 'Borealis Mining',            country: 'CA', reliability_score: 0.79, founded_year: 1996, employees: 880});
CREATE (:Supplier {supplier_id: 'SUP-011', name: 'Sapphire Optics',            country: 'JP', reliability_score: 0.95, founded_year: 1972, employees: 1450});
CREATE (:Supplier {supplier_id: 'SUP-012', name: 'Atlas Heavy Machinery',      country: 'JP', reliability_score: 0.91, founded_year: 1960, employees: 2300});
CREATE (:Supplier {supplier_id: 'SUP-013', name: 'Zenith Plastics',            country: 'CN', reliability_score: 0.76, founded_year: 2001, employees: 950});
CREATE (:Supplier {supplier_id: 'SUP-014', name: 'Solstice Manufacturing',     country: 'CN', reliability_score: 0.73, founded_year: 2005, employees: 1200});
CREATE (:Supplier {supplier_id: 'SUP-015', name: 'Helios Energy Components',   country: 'SG', reliability_score: 0.88, founded_year: 1989, employees: 410});
CREATE (:Supplier {supplier_id: 'SUP-016', name: 'Crimson Aerospace',          country: 'FR', reliability_score: 0.94, founded_year: 1968, employees: 5800});
CREATE (:Supplier {supplier_id: 'SUP-017', name: 'Avalanche Industrial',       country: 'DE', reliability_score: 0.86, founded_year: 1979, employees: 650});
CREATE (:Supplier {supplier_id: 'SUP-018', name: 'Catalyst Specialty Polymers',country: 'US', reliability_score: 0.92, founded_year: 1984, employees: 480});
CREATE (:Supplier {supplier_id: 'SUP-019', name: 'Diamondback Drilling',       country: 'US', reliability_score: 0.81, founded_year: 1992, employees: 340});
CREATE (:Supplier {supplier_id: 'SUP-020', name: 'Eclipse Precision Tools',    country: 'GB', reliability_score: 0.90, founded_year: 1965, employees: 280});

// ---- Holding companies (intermediary layer that creates the indirect ----
// ---- ownership trails the proximity traversal will surface) -------------
CREATE (:HoldingCompany {holding_id: 'HOLD-001', name: 'Apex Holdings International',  country: 'US'});
CREATE (:HoldingCompany {holding_id: 'HOLD-002', name: 'Crestfall Pacific Ventures',   country: 'HK'});
CREATE (:HoldingCompany {holding_id: 'HOLD-003', name: 'Onyx Asia Holdings',           country: 'SG'});
CREATE (:HoldingCompany {holding_id: 'HOLD-004', name: 'Zenith Group International',   country: 'CN'});

// ---- Sanctioned-network entities (5) — graph-resident sanctions data ---
// Distinct from tcs_core.SanctionedEntity which is the OFAC SDN feed in CSV;
// these are the shell companies / front entities that LINK to suppliers via
// indirect ownership. The proximity traversal is the demo-critical query.
CREATE (:SanctionedNetworkEntity {entity_id: 'SDN-NET-001', name: 'Shengli Shell Trading',    program: 'OFAC SDN', country: 'CN', listed_at: '2024-03-12', risk_tier: 'HIGH'});
CREATE (:SanctionedNetworkEntity {entity_id: 'SDN-NET-002', name: 'Karaganda Mining Holdings',program: 'OFAC SDN', country: 'KZ', listed_at: '2025-01-18', risk_tier: 'HIGH'});
CREATE (:SanctionedNetworkEntity {entity_id: 'SDN-NET-003', name: 'Atlas Bay Logistics',      program: 'OFAC SDN', country: 'MY', listed_at: '2024-09-04', risk_tier: 'MEDIUM'});
CREATE (:SanctionedNetworkEntity {entity_id: 'SDN-NET-004', name: 'Pearl River Investments',  program: 'OFAC SDN', country: 'CN', listed_at: '2025-04-22', risk_tier: 'HIGH'});
CREATE (:SanctionedNetworkEntity {entity_id: 'SDN-NET-005', name: 'Sakhalin Petroleum Trade', program: 'OFAC SDN', country: 'RU', listed_at: '2023-11-30', risk_tier: 'CRITICAL'});

// ---- Carriers (8) — mirror carriers.csv ids so the graph joins to CSV --
CREATE (:Carrier {carrier_id: 'CR-MAEU', name: 'Maersk',              scac: 'MAEU'});
CREATE (:Carrier {carrier_id: 'CR-MSCU', name: 'MSC',                 scac: 'MSCU'});
CREATE (:Carrier {carrier_id: 'CR-HLCU', name: 'Hapag-Lloyd',         scac: 'HLCU'});
CREATE (:Carrier {carrier_id: 'CR-CMDU', name: 'CMA CGM',             scac: 'CMDU'});
CREATE (:Carrier {carrier_id: 'CR-COSU', name: 'COSCO Shipping',      scac: 'COSU'});
CREATE (:Carrier {carrier_id: 'CR-ONEY', name: 'Ocean Network Express',scac: 'ONEY'});
CREATE (:Carrier {carrier_id: 'CR-EGLV', name: 'Evergreen Marine',    scac: 'EGLV'});
CREATE (:Carrier {carrier_id: 'CR-ZIMU', name: 'ZIM Integrated Shipping',scac: 'ZIMU'});

// ---- Alliances (3) — real ocean-alliance names ------------------------
CREATE (:Alliance {alliance_id: 'ALL-2M',    name: '2M Alliance',     known_for: 'Mediterranean + Asia-Europe capacity concentration'});
CREATE (:Alliance {alliance_id: 'ALL-OCEAN', name: 'Ocean Alliance',  known_for: 'Transpacific dominance · multi-flag carriers'});
CREATE (:Alliance {alliance_id: 'ALL-THE',   name: 'THE Alliance',    known_for: 'Asia-North-America secondary route share'});

// =============================================================================
// Relationships
// =============================================================================

// ---- Corporate parent/subsidiary chains ----
MATCH (parent:Supplier {supplier_id: 'SUP-002'}), (child:Supplier {supplier_id: 'SUP-001'})
CREATE (parent)-[:PARENT_OF {since: '1998-06-01'}]->(child);

MATCH (parent:Supplier {supplier_id: 'SUP-006'}), (child:Supplier {supplier_id: 'SUP-005'})
CREATE (parent)-[:PARENT_OF {since: '2011-03-15'}]->(child);

MATCH (parent:Supplier {supplier_id: 'SUP-009'}), (child:Supplier {supplier_id: 'SUP-008'})
CREATE (parent)-[:PARENT_OF {since: '2002-09-22'}]->(child);

MATCH (parent:Supplier {supplier_id: 'SUP-011'}), (child:Supplier {supplier_id: 'SUP-012'})
CREATE (parent)-[:PARENT_OF {since: '2009-11-04'}]->(child);

// ---- Joint ventures ----
MATCH (a:Supplier {supplier_id: 'SUP-001'}), (b:Supplier {supplier_id: 'SUP-003'})
CREATE (a)-[:JOINT_VENTURE_WITH {since: '2019-04-10', share: 0.45}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-006'}), (b:Supplier {supplier_id: 'SUP-007'})
CREATE (a)-[:JOINT_VENTURE_WITH {since: '2015-08-22', share: 0.30}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-016'}), (b:Supplier {supplier_id: 'SUP-018'})
CREATE (a)-[:JOINT_VENTURE_WITH {since: '2021-01-12', share: 0.50}]->(b);

// ---- Supplier ownership of holding companies ----
MATCH (s:Supplier {supplier_id: 'SUP-002'}), (h:HoldingCompany {holding_id: 'HOLD-001'})
CREATE (s)-[:CONTROLLED_BY {pct: 100, since: '1962-01-01'}]->(h);

MATCH (s:Supplier {supplier_id: 'SUP-006'}), (h:HoldingCompany {holding_id: 'HOLD-002'})
CREATE (s)-[:CONTROLLED_BY {pct: 78, since: '2008-05-19'}]->(h);

MATCH (s:Supplier {supplier_id: 'SUP-009'}), (h:HoldingCompany {holding_id: 'HOLD-003'})
CREATE (s)-[:CONTROLLED_BY {pct: 65, since: '2003-02-14'}]->(h);

MATCH (s:Supplier {supplier_id: 'SUP-013'}), (h:HoldingCompany {holding_id: 'HOLD-004'})
CREATE (s)-[:CONTROLLED_BY {pct: 100, since: '2001-01-01'}]->(h);

MATCH (s:Supplier {supplier_id: 'SUP-014'}), (h:HoldingCompany {holding_id: 'HOLD-004'})
CREATE (s)-[:CONTROLLED_BY {pct: 100, since: '2005-06-30'}]->(h);

// Sibling-density boost — extra CONTROLLED_BY edges so the
// alternative-supplier-discovery scenario has more than one candidate per
// blocked supplier. Each holding now controls 2-3 suppliers instead of 1.
MATCH (s:Supplier {supplier_id: 'SUP-015'}), (h:HoldingCompany {holding_id: 'HOLD-001'})
CREATE (s)-[:CONTROLLED_BY {pct: 60, since: '2011-09-15'}]->(h);

MATCH (s:Supplier {supplier_id: 'SUP-007'}), (h:HoldingCompany {holding_id: 'HOLD-002'})
CREATE (s)-[:CONTROLLED_BY {pct: 45, since: '2013-02-04'}]->(h);

MATCH (s:Supplier {supplier_id: 'SUP-019'}), (h:HoldingCompany {holding_id: 'HOLD-004'})
CREATE (s)-[:CONTROLLED_BY {pct: 50, since: '2017-11-21'}]->(h);

// Cross-group JV — so the alt-supplier scenario also picks up partners
// outside the controlling holding.
MATCH (a:Supplier {supplier_id: 'SUP-013'}), (b:Supplier {supplier_id: 'SUP-019'})
CREATE (a)-[:JOINT_VENTURE_WITH {since: '2020-03-08', share: 0.35}]->(b);

// ---- Multi-tier supply chains (SOURCES_FROM -> upstream Supplier) -------
// Each edge means "this Supplier sources material from THAT upstream
// Supplier." Used by the Tier-N visibility scenario to walk a product's
// supply chain back through 2-4 tiers and surface dependencies that flat
// PO tables can't see.
MATCH (a:Supplier {supplier_id: 'SUP-001'}), (b:Supplier {supplier_id: 'SUP-002'})
CREATE (a)-[:SOURCES_FROM {material: 'alloy bars', since: '2018-01-15'}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-001'}), (b:Supplier {supplier_id: 'SUP-004'})
CREATE (a)-[:SOURCES_FROM {material: 'casting coolant', since: '2020-06-01'}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-002'}), (b:Supplier {supplier_id: 'SUP-013'})
CREATE (a)-[:SOURCES_FROM {material: 'iron ore concentrate', since: '2015-04-22'}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-002'}), (b:Supplier {supplier_id: 'SUP-010'})
CREATE (a)-[:SOURCES_FROM {material: 'silica flux', since: '2019-11-08'}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-006'}), (b:Supplier {supplier_id: 'SUP-007'})
CREATE (a)-[:SOURCES_FROM {material: 'cast blanks', since: '2016-07-30'}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-007'}), (b:Supplier {supplier_id: 'SUP-013'})
CREATE (a)-[:SOURCES_FROM {material: 'iron ore', since: '2014-09-12'}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-013'}), (b:Supplier {supplier_id: 'SUP-019'})
CREATE (a)-[:SOURCES_FROM {material: 'drill consumables', since: '2017-02-18'}]->(b);

MATCH (a:Supplier {supplier_id: 'SUP-005'}), (b:Supplier {supplier_id: 'SUP-003'})
CREATE (a)-[:SOURCES_FROM {material: 'forged blanks', since: '2013-12-04'}]->(b);

// ---- Holding company stakes in sanctioned-network entities (the trail) --
// Hemlock Precision Castings → Apex Metalworks → Apex Holdings International
//   → 22% of Shengli Shell Trading (OFAC SDN).
// Two hops from Hemlock, three from Hemlock-to-SDN. THIS is the proximity
// signal that the agent surfaces during onboarding.
MATCH (h:HoldingCompany {holding_id: 'HOLD-001'}), (sdn:SanctionedNetworkEntity {entity_id: 'SDN-NET-001'})
CREATE (h)-[:OWNS_SHARE {pct: 22, acquired: '2021-07-14'}]->(sdn);

// Crestfall Pacific Ventures → 31% of Pearl River Investments (CN SDN).
MATCH (h:HoldingCompany {holding_id: 'HOLD-002'}), (sdn:SanctionedNetworkEntity {entity_id: 'SDN-NET-004'})
CREATE (h)-[:OWNS_SHARE {pct: 31, acquired: '2019-03-08'}]->(sdn);

// Onyx Asia Holdings → 18% of Sakhalin Petroleum Trade (RU CRITICAL SDN).
MATCH (h:HoldingCompany {holding_id: 'HOLD-003'}), (sdn:SanctionedNetworkEntity {entity_id: 'SDN-NET-005'})
CREATE (h)-[:OWNS_SHARE {pct: 18, acquired: '2020-11-02'}]->(sdn);

// Zenith Group International → 40% of Shengli Shell Trading.
MATCH (h:HoldingCompany {holding_id: 'HOLD-004'}), (sdn:SanctionedNetworkEntity {entity_id: 'SDN-NET-001'})
CREATE (h)-[:OWNS_SHARE {pct: 40, acquired: '2018-09-25'}]->(sdn);

// Borealis Mining → direct 12% in Karaganda Mining Holdings.
MATCH (s:Supplier {supplier_id: 'SUP-010'}), (sdn:SanctionedNetworkEntity {entity_id: 'SDN-NET-002'})
CREATE (s)-[:OWNS_SHARE {pct: 12, acquired: '2022-04-19'}]->(sdn);

// ---- Supplier shipping preferences (SHIPS_VIA -> Carrier) --------------
// Mirrors what carriers.csv already knows but adds the supplier→carrier
// preference edge that doesn't exist anywhere else.
MATCH (s:Supplier {supplier_id: 'SUP-001'}), (c:Carrier {carrier_id: 'CR-COSU'})
CREATE (s)-[:SHIPS_VIA {primary: true, lane_share: 0.65}]->(c);
MATCH (s:Supplier {supplier_id: 'SUP-001'}), (c:Carrier {carrier_id: 'CR-CMDU'})
CREATE (s)-[:SHIPS_VIA {primary: false, lane_share: 0.20}]->(c);

MATCH (s:Supplier {supplier_id: 'SUP-002'}), (c:Carrier {carrier_id: 'CR-MAEU'})
CREATE (s)-[:SHIPS_VIA {primary: true, lane_share: 0.80}]->(c);

MATCH (s:Supplier {supplier_id: 'SUP-005'}), (c:Carrier {carrier_id: 'CR-EGLV'})
CREATE (s)-[:SHIPS_VIA {primary: true, lane_share: 0.55}]->(c);
MATCH (s:Supplier {supplier_id: 'SUP-005'}), (c:Carrier {carrier_id: 'CR-COSU'})
CREATE (s)-[:SHIPS_VIA {primary: false, lane_share: 0.30}]->(c);

MATCH (s:Supplier {supplier_id: 'SUP-006'}), (c:Carrier {carrier_id: 'CR-MSCU'})
CREATE (s)-[:SHIPS_VIA {primary: true, lane_share: 0.70}]->(c);

MATCH (s:Supplier {supplier_id: 'SUP-008'}), (c:Carrier {carrier_id: 'CR-HLCU'})
CREATE (s)-[:SHIPS_VIA {primary: true, lane_share: 0.60}]->(c);

MATCH (s:Supplier {supplier_id: 'SUP-013'}), (c:Carrier {carrier_id: 'CR-COSU'})
CREATE (s)-[:SHIPS_VIA {primary: true, lane_share: 0.85}]->(c);

MATCH (s:Supplier {supplier_id: 'SUP-014'}), (c:Carrier {carrier_id: 'CR-EGLV'})
CREATE (s)-[:SHIPS_VIA {primary: true, lane_share: 0.50}]->(c);
MATCH (s:Supplier {supplier_id: 'SUP-014'}), (c:Carrier {carrier_id: 'CR-COSU'})
CREATE (s)-[:SHIPS_VIA {primary: false, lane_share: 0.40}]->(c);

// ---- Alliance memberships (MEMBER_OF -> Alliance) ----------------------
MATCH (c:Carrier {carrier_id: 'CR-MAEU'}), (a:Alliance {alliance_id: 'ALL-2M'})
CREATE (c)-[:MEMBER_OF {since: '2015-01-01'}]->(a);
MATCH (c:Carrier {carrier_id: 'CR-MSCU'}), (a:Alliance {alliance_id: 'ALL-2M'})
CREATE (c)-[:MEMBER_OF {since: '2015-01-01'}]->(a);

MATCH (c:Carrier {carrier_id: 'CR-CMDU'}), (a:Alliance {alliance_id: 'ALL-OCEAN'})
CREATE (c)-[:MEMBER_OF {since: '2017-04-01'}]->(a);
MATCH (c:Carrier {carrier_id: 'CR-COSU'}), (a:Alliance {alliance_id: 'ALL-OCEAN'})
CREATE (c)-[:MEMBER_OF {since: '2017-04-01'}]->(a);
MATCH (c:Carrier {carrier_id: 'CR-EGLV'}), (a:Alliance {alliance_id: 'ALL-OCEAN'})
CREATE (c)-[:MEMBER_OF {since: '2017-04-01'}]->(a);

MATCH (c:Carrier {carrier_id: 'CR-HLCU'}), (a:Alliance {alliance_id: 'ALL-THE'})
CREATE (c)-[:MEMBER_OF {since: '2017-04-01'}]->(a);
MATCH (c:Carrier {carrier_id: 'CR-ONEY'}), (a:Alliance {alliance_id: 'ALL-THE'})
CREATE (c)-[:MEMBER_OF {since: '2017-04-01'}]->(a);

// ---- A few PurchaseOrders + Products for backward compat with the ------
// ---- pre-existing SC-ONTO-supply_chain-{PurchaseOrder,Product} chips ---
CREATE (:PurchaseOrder {po_id: 'PO-2026-0114', total_value: 184000, placed_on: '2026-02-08'});
CREATE (:PurchaseOrder {po_id: 'PO-2026-0182', total_value: 312500, placed_on: '2026-03-21'});
CREATE (:PurchaseOrder {po_id: 'PO-2026-0287', total_value: 95800,  placed_on: '2026-04-04'});

CREATE (:Product {product_id: 'P-EL-9001', name: 'Encryption Module Mk II', category: 'electronics'});
CREATE (:Product {product_id: 'P-MC-7100', name: 'Tier-1 cast housing',     category: 'castings'});
CREATE (:Product {product_id: 'P-MC-7101', name: 'Tier-1 cast bracket',     category: 'castings'});

MATCH (s:Supplier {supplier_id: 'SUP-001'}), (po:PurchaseOrder {po_id: 'PO-2026-0114'})
CREATE (s)-[:PLACED]->(po);
MATCH (s:Supplier {supplier_id: 'SUP-002'}), (po:PurchaseOrder {po_id: 'PO-2026-0182'})
CREATE (s)-[:PLACED]->(po);
MATCH (s:Supplier {supplier_id: 'SUP-006'}), (po:PurchaseOrder {po_id: 'PO-2026-0287'})
CREATE (s)-[:PLACED]->(po);

MATCH (po:PurchaseOrder {po_id: 'PO-2026-0114'}), (p:Product {product_id: 'P-EL-9001'})
CREATE (po)-[:CONTAINS]->(p);
MATCH (po:PurchaseOrder {po_id: 'PO-2026-0182'}), (p:Product {product_id: 'P-MC-7100'})
CREATE (po)-[:CONTAINS]->(p);
MATCH (po:PurchaseOrder {po_id: 'PO-2026-0287'}), (p:Product {product_id: 'P-MC-7101'})
CREATE (po)-[:CONTAINS]->(p);
