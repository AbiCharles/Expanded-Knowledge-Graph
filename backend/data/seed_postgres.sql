-- Postgres equivalent of governance.sqlite — same schema, same rows.
-- Run against a fresh database:
--   docker compose -f docker-compose.postgres.yaml up -d
--   psql "postgresql://hitl:hitl@localhost:5432/governance" -f backend/data/seed_postgres.sql

DROP TABLE IF EXISTS prior_cases;

CREATE TABLE prior_cases (
    case_id      TEXT PRIMARY KEY,
    scenario_id  TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    rationale    TEXT NOT NULL,
    decided_by   TEXT NOT NULL,
    decided_at   DATE NOT NULL
);

CREATE INDEX idx_prior_cases_scenario ON prior_cases(scenario_id);

INSERT INTO prior_cases (case_id, scenario_id, outcome, rationale, decided_by, decided_at) VALUES
  ('PR-2026-Q1-088', 'SC-TC-007', 'rejected',                'End-user could not be verified',                                 'compliance.officer.kchen',   CURRENT_DATE - 30),
  ('PR-2026-Q1-061', 'SC-TC-007', 'approved_with_conditions','Customer provided valid OFAC license; license number recorded',   'compliance.officer.kchen',   CURRENT_DATE - 55),
  ('PR-2025-Q4-217', 'SC-TC-007', 'rejected',                'Pattern of override requests from same customer; escalated',     'legal.counsel.rmehta',       CURRENT_DATE - 110),
  ('PR-2025-Q4-184', 'SC-TC-007', 'approved',                'Standalone case; full diligence package on file',                'compliance.officer.tnguyen', CURRENT_DATE - 134),
  ('PR-2026-Q1-105', 'SC-PP-007', 'approved',                'ISO 9001 audit clean; ESG above threshold',                      'procurement.lead.amorales',  CURRENT_DATE - 22),
  ('PR-2026-Q1-073', 'SC-PP-007', 'rejected',                'Capacity assessment insufficient for tier-1 commitment',         'procurement.lead.amorales',  CURRENT_DATE - 48),
  ('PR-2025-Q4-291', 'SC-PP-007', 'more_info_requested',     'Reference customer interviews requested before re-review',       'procurement.lead.amorales',  CURRENT_DATE - 89),
  ('PR-2025-Q3-152', 'SC-PP-007', 'approved',                'Strong financials; sole-source risk acknowledged in record',     'procurement.lead.amorales',  CURRENT_DATE - 178),
  ('PR-2026-Q1-211', 'SC-LN-002', 'approved',                'Customer SLA exposure justified one-time air upgrade',           'logistics.planner.lead',     CURRENT_DATE - 18),
  ('PR-2026-Q1-189', 'SC-LN-002', 'rejected',                'Recurring lane pattern; structural review required first',       'logistics.planner.lead',     CURRENT_DATE - 35),
  ('PR-2025-Q4-322', 'SC-LN-002', 'rejected',                'Cost recovery insufficient given budget envelope',               'logistics.planner.lead',     CURRENT_DATE - 122),
  ('PR-2025-Q4-298', 'SC-LN-002', 'approved',                'Force majeure event upstream; one-time exception granted',       'logistics.planner.lead',     CURRENT_DATE - 145);
