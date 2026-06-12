/**
 * Phase 2 — LoadBearingFactsPicker (exercised via RationaleModal).
 *
 * Covers:
 *   - Pick / unpick a fact (toggle)
 *   - Cap of 3 highlights enforced in the UI
 *   - Submitting passes the picked refs through to onSubmit
 *   - "No facts" → picker doesn't render (avoids dead UI on empty stages)
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RationaleModal } from "../Modals";
import type { CaseFull, FactRow } from "../../types";

function makeFact(overrides: Partial<FactRow> & { id: string }): FactRow {
  return {
    id: overrides.id,
    ontology_type: overrides.ontology_type || "Product",
    source: overrides.source || "csv:products_csv",
    uri: null,
    title: overrides.title || `Title-${overrides.id}`,
    summary: null,
    query_index: 0,
  };
}

function makeCase(facts: FactRow[]): CaseFull {
  return {
    case_id: "C-001",
    scenario_id: "SC-PP-008",
    scenario_version: 3,
    phase: "review_ready",
    actor: null,
    lineage: [],
    stages: [{ stage: "proposal", binder: "default", facts }],
    scenario: {
      title: "Supplier onboarding",
      rationale_reasons: { reject: ["Reason A", "Reason B"] },
    } as any,
  } as unknown as CaseFull;
}

describe("LoadBearingFactsPicker (via RationaleModal)", () => {
  it("renders one chip per fact across all stages", () => {
    const facts = [
      makeFact({ id: "P-1" }),
      makeFact({ id: "P-2" }),
      makeFact({ id: "P-3" }),
    ];
    render(
      <RationaleModal
        active={makeCase(facts)}
        decision="reject"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText(/Which facts were load-bearing/i)).toBeInTheDocument();
    expect(screen.getByText("P-1")).toBeInTheDocument();
    expect(screen.getByText("P-2")).toBeInTheDocument();
    expect(screen.getByText("P-3")).toBeInTheDocument();
    expect(screen.getByText(/\(0\/3\)/)).toBeInTheDocument();
  });

  it("hides the picker when no facts are available", () => {
    render(
      <RationaleModal
        active={makeCase([])}
        decision="reject"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Which facts were load-bearing/i)).not.toBeInTheDocument();
  });

  it("caps selection at 3 and disables further chips at the cap", async () => {
    const user = userEvent.setup();
    render(
      <RationaleModal
        active={makeCase([
          makeFact({ id: "P-1" }),
          makeFact({ id: "P-2" }),
          makeFact({ id: "P-3" }),
          makeFact({ id: "P-4" }),
        ])}
        decision="reject"
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /P-1/ }));
    await user.click(screen.getByRole("button", { name: /P-2/ }));
    await user.click(screen.getByRole("button", { name: /P-3/ }));
    expect(screen.getByText(/\(3\/3\)/)).toBeInTheDocument();

    const p4 = screen.getByRole("button", { name: /P-4/ });
    expect(p4).toBeDisabled();

    // Unpick P-1 → cap freed → P-4 selectable again.
    await user.click(screen.getByRole("button", { name: /P-1/ }));
    expect(screen.getByText(/\(2\/3\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /P-4/ })).not.toBeDisabled();
  });

  it("passes picked refs into onSubmit in selection order", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <RationaleModal
        active={makeCase([
          makeFact({ id: "P-1", ontology_type: "Product" }),
          makeFact({ id: "P-2", ontology_type: "Supplier" }),
        ])}
        decision="reject"
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    // Pick in order: P-2 then P-1.
    await user.click(screen.getByRole("button", { name: /P-2/ }));
    await user.click(screen.getByRole("button", { name: /P-1/ }));

    // Fill rationale (>= 4 chars) and continue → submit.
    const textarea = screen.getByPlaceholderText(/Type or edit the reason/i);
    await user.type(textarea, "Sanctions proximity too close");
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    await user.click(screen.getByRole("button", { name: /Yes, reject/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const refs = onSubmit.mock.calls[0][2];
    expect(refs).toHaveLength(2);
    expect(refs[0].id).toBe("P-2");
    expect(refs[1].id).toBe("P-1");
    expect(refs[0].ontology_type).toBe("Supplier");
  });
});
