# Mode-Switch Policy — Logistics & Network

## Statement
Switching a shipment from its booked mode to an expedited mode (typically ocean → air) is permitted within the standing 25% cost-uplift envelope per shipment, but **always requires planner approval** regardless of cost.

## Rationale
Repeated mode switches on the same lane are a leading indicator of structural problems (carrier reliability, inventory positioning, demand forecast error). Catching the pattern at point-of-decision is cheaper than discovering it through quarterly cost reviews.

## Approval criteria
The reviewing planner should consider:
1. **Customer SLA exposure** — what is the late-delivery penalty?
2. **Lane history** — how many switches on this lane in the last 30 days? More than 3 is a flag.
3. **Alternative carriers** — is there an alternative ocean carrier that could meet the schedule with less uplift?
4. **Structural lane review status** — has the planning team flagged this lane for structural review? If yes, prefer holding the original booking and escalating instead.

## Cost envelope
Switches with cost uplift > 25% require additional approval from the logistics director. Switches > 50% require SVP Operations.

## Audit
Every mode switch creates a lineage event in the case file. Quarterly review summarises by lane.
