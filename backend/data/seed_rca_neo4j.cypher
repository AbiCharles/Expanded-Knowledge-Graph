// Manufacturing-RCA evidence graph seed.
// Backs the manufacturing_rca ontology's Part / Defect / EvidenceNode
// classes (see backend/ontologies/manufacturing_rca.mappings.yaml).
// The narrative: a high-severity delamination (DEF-1234) on a Mirage-program
// wing-spar (P-1234) whose evidence chain walks visual + log findings →
// an inference → a root cause.
//
// Load with, e.g.:
//   docker exec -i tcs_kf_neo4j cypher-shell -u neo4j -p <pw> < backend/data/seed_rca_neo4j.cypher
//
// Idempotent: MERGE on stable ids so re-running is safe. Each statement is
// self-contained (matches its endpoints by id) because cypher-shell runs
// every ;-terminated statement in its own scope — variables do NOT carry
// across statements.

// --- Part + Defect -----------------------------------------------------------
MERGE (p:Part {part_id: 'P-1234'})
  SET p.name = 'Wing spar composite panel',
      p.material = 'CFRP (carbon/epoxy)',
      p.program = 'Mirage';

MERGE (d:Defect {defect_id: 'DEF-1234'})
  SET d.part_id = 'P-1234',
      d.defect_type = 'delamination',
      d.severity = 'high',
      d.location = 'ply 7/8 interface, inboard bay 3',
      d.program = 'Mirage';

MATCH (p:Part {part_id: 'P-1234'}), (d:Defect {defect_id: 'DEF-1234'})
MERGE (p)-[:HAS_DEFECT]->(d);

// --- Evidence nodes ----------------------------------------------------------
MERGE (ev:EvidenceNode {node_id: 'EV-V1'})
  SET ev.part_id = 'P-1234', ev.node_type = 'visual',
      ev.description = 'C-scan shows an 18mm delamination at the ply 7/8 interface',
      ev.evidence_source = 'C-scan image', ev.confidence = 92;
MERGE (el1:EvidenceNode {node_id: 'EV-L1'})
  SET el1.part_id = 'P-1234', el1.node_type = 'log',
      el1.description = 'Autoclave pressure dropped 12% below setpoint during the cure hold',
      el1.evidence_source = 'autoclave_telemetry', el1.confidence = 88;
MERGE (el2:EvidenceNode {node_id: 'EV-L2'})
  SET el2.part_id = 'P-1234', el2.node_type = 'log',
      el2.description = 'Vacuum bag leak rate exceeded 2 inHg/min at the pre-cure bag check',
      el2.evidence_source = 'layup_qc_log', el2.confidence = 74;
MERGE (ei1:EvidenceNode {node_id: 'EV-I1'})
  SET ei1.part_id = 'P-1234', ei1.node_type = 'inference',
      ei1.description = 'Insufficient consolidation pressure during cure',
      ei1.evidence_source = 'RCA inference', ei1.confidence = 81;
MERGE (er1:EvidenceNode {node_id: 'EV-R1'})
  SET er1.part_id = 'P-1234', er1.node_type = 'root_cause',
      er1.description = 'Autoclave pressure regulator drifted out of calibration',
      er1.evidence_source = 'maintenance record MR-8842', er1.confidence = 79;

// --- Defect -> evidence chain (match endpoints by id) ------------------------
MATCH (d:Defect {defect_id: 'DEF-1234'}), (e:EvidenceNode {node_id: 'EV-V1'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-1234'}), (e:EvidenceNode {node_id: 'EV-L1'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-1234'}), (e:EvidenceNode {node_id: 'EV-L2'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-1234'}), (e:EvidenceNode {node_id: 'EV-I1'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-1234'}), (e:EvidenceNode {node_id: 'EV-R1'}) MERGE (d)-[:EVIDENCED_BY]->(e);

// --- Causal edges (for future GraphViz traversal) ----------------------------
MATCH (a:EvidenceNode {node_id: 'EV-V1'}), (b:EvidenceNode {node_id: 'EV-I1'}) MERGE (a)-[:SUPPORTS {strength: 85}]->(b);
MATCH (a:EvidenceNode {node_id: 'EV-L1'}), (b:EvidenceNode {node_id: 'EV-I1'}) MERGE (a)-[:SUPPORTS {strength: 90}]->(b);
MATCH (a:EvidenceNode {node_id: 'EV-L2'}), (b:EvidenceNode {node_id: 'EV-I1'}) MERGE (a)-[:SUPPORTS {strength: 60}]->(b);
MATCH (a:EvidenceNode {node_id: 'EV-I1'}), (b:EvidenceNode {node_id: 'EV-R1'}) MERGE (a)-[:INDICATES {strength: 78}]->(b);

// ============================================================================
// Second part — P-3300, a delamination on the Viper horizontal-stabilizer skin
// (a genuinely different investigation: different part, program, and cause).
// ============================================================================
MERGE (p:Part {part_id: 'P-3300'})
  SET p.name = 'Horizontal stabilizer skin panel',
      p.material = 'CFRP (carbon/epoxy)',
      p.program = 'Viper';

MERGE (d:Defect {defect_id: 'DEF-3300'})
  SET d.part_id = 'P-3300',
      d.defect_type = 'delamination',
      d.severity = 'medium',
      d.location = 'skin-to-doubler interface, station 220',
      d.program = 'Viper';

MATCH (p:Part {part_id: 'P-3300'}), (d:Defect {defect_id: 'DEF-3300'})
MERGE (p)-[:HAS_DEFECT]->(d);

MERGE (ev:EvidenceNode {node_id: 'EV3-V1'})
  SET ev.part_id = 'P-3300', ev.node_type = 'visual',
      ev.description = 'C-scan shows a 9mm delamination at the skin/doubler bondline',
      ev.evidence_source = 'C-scan image', ev.confidence = 87;
MERGE (el1:EvidenceNode {node_id: 'EV3-L1'})
  SET el1.part_id = 'P-3300', el1.node_type = 'log',
      el1.description = 'Cure temperature undershoot 9C below profile at the hold',
      el1.evidence_source = 'autoclave_telemetry', el1.confidence = 84;
MERGE (el2:EvidenceNode {node_id: 'EV3-L2'})
  SET el2.part_id = 'P-3300', el2.node_type = 'log',
      el2.description = 'Vacuum lost to 12 inHg during the first cure ramp',
      el2.evidence_source = 'autoclave_telemetry', el2.confidence = 76;
MERGE (ei1:EvidenceNode {node_id: 'EV3-I1'})
  SET ei1.part_id = 'P-3300', ei1.node_type = 'inference',
      ei1.description = 'Under-cure plus vacuum loss left the bondline under-consolidated',
      ei1.evidence_source = 'RCA inference', ei1.confidence = 80;
MERGE (er1:EvidenceNode {node_id: 'EV3-R1'})
  SET er1.part_id = 'P-3300', er1.node_type = 'root_cause',
      er1.description = 'Autoclave thermocouple lag produced a cold cure cycle',
      er1.evidence_source = 'maintenance record MR-9107', er1.confidence = 78;

MATCH (d:Defect {defect_id: 'DEF-3300'}), (e:EvidenceNode {node_id: 'EV3-V1'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-3300'}), (e:EvidenceNode {node_id: 'EV3-L1'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-3300'}), (e:EvidenceNode {node_id: 'EV3-L2'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-3300'}), (e:EvidenceNode {node_id: 'EV3-I1'}) MERGE (d)-[:EVIDENCED_BY]->(e);
MATCH (d:Defect {defect_id: 'DEF-3300'}), (e:EvidenceNode {node_id: 'EV3-R1'}) MERGE (d)-[:EVIDENCED_BY]->(e);

MATCH (a:EvidenceNode {node_id: 'EV3-V1'}), (b:EvidenceNode {node_id: 'EV3-I1'}) MERGE (a)-[:SUPPORTS {strength: 82}]->(b);
MATCH (a:EvidenceNode {node_id: 'EV3-L1'}), (b:EvidenceNode {node_id: 'EV3-I1'}) MERGE (a)-[:SUPPORTS {strength: 88}]->(b);
MATCH (a:EvidenceNode {node_id: 'EV3-L2'}), (b:EvidenceNode {node_id: 'EV3-I1'}) MERGE (a)-[:SUPPORTS {strength: 64}]->(b);
MATCH (a:EvidenceNode {node_id: 'EV3-I1'}), (b:EvidenceNode {node_id: 'EV3-R1'}) MERGE (a)-[:INDICATES {strength: 75}]->(b);
