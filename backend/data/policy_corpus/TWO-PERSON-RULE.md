# Two-Person Rule for Critical Overrides

## When the two-person rule applies
For any of the following actions, two named compliance officers (or in the case of procurement, the category manager plus the procurement director) must concur before the action proceeds:

- Trade-compliance overrides on encryption-controlled products (ECCN 5A002, 5D002)
- FPGA / programmable logic exports (ECCN 3A001)
- Robotics and machine-tool exports above $50k (ECCN 2B001)
- Vendor onboarding for tier-1 strategic suppliers above USD 1M annual spend
- Mode-switch decisions involving a cost uplift greater than 25% of baseline freight cost

## Procedure
1. The first reviewer captures their decision and rationale in the audit log.
2. The case file is then routed to the second reviewer with full bound context preserved.
3. The second reviewer reviews independently. If they concur, the action proceeds. If not, the action is rejected and routed to a third-party arbiter (legal counsel for trade compliance; CPO for procurement; SVP Operations for logistics).

## Auditability
Both reviewers' identities, decisions, and rationales must appear in the lineage chain. Replay must reproduce both decisions in order.
