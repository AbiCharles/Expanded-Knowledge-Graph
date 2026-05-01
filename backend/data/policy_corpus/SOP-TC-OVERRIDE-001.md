# SOP-TC-OVERRIDE-001 — Trade Compliance Override Standard Operating Procedure

## Purpose
This SOP governs operator and agent requests to override an active trade-compliance guardrail (e.g. SC-TC-001 sanctions block, SC-TC-002 ECCN restriction). Critical overrides are not delegable to autonomous agents.

## Scope
Applies to any proposed action that would proceed despite a `BLOCK` decision from a trade-compliance guardrail. Includes sanctions, export controls, dual-use technology restrictions, and embargoed-country shipments.

## Required steps before override

1. **Verify the underlying license.** The customer or counterparty must provide a current, named OFAC general or specific license. Capture the license number, expiry, and issuing agency in the case file.
2. **Confirm end-use.** Document the intended end-use of the controlled product. End-user must be a named entity, not a broker or unnamed third party.
3. **Document rationale.** The reviewing compliance officer records (a) why the override is appropriate, (b) what residual risk remains, (c) what mitigations are in place.
4. **Two-person rule.** A second compliance officer must concur on overrides for products with ECCN classifications in the 5A002, 3A001, or 2B001 categories.

## Rejection criteria
- License documentation cannot be verified independently
- End-user cannot be identified or is itself listed on a sanctions list
- Pattern of repeat override requests for the same customer
- Compliance officer has any unresolved doubt — when in doubt, deny

## Audit trail
Every override decision is recorded in the governance audit store with the bound knowledge envelope, the reviewer's rationale, and the time-stamped decision. Replayable for audit by the compliance team or external regulators.
