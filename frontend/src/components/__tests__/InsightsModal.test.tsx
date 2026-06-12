/**
 * Phase 3a — InsightsModal renders the aggregate from /api/insights/patterns.
 *
 * Covers:
 *   - Empty state (no reviewer signal yet) — no scenario rows
 *   - Populated: scenarios render with pattern rows + percentages
 *   - Esc closes the modal
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { InsightsModal } from "../InsightsModal";
import * as api from "../../api";

vi.mock("../../api", () => ({
  getInsightsPatterns: vi.fn(),
}));

const getPatterns = api.getInsightsPatterns as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InsightsModal", () => {
  it("renders the empty-state hint when no scenarios come back", async () => {
    getPatterns.mockResolvedValue({ generated_at_seconds: 1, scenarios: [] });
    render(<InsightsModal onClose={vi.fn()} />);
    expect(await screen.findByText(/No reviewer signal yet/i)).toBeInTheDocument();
  });

  it("renders one scenario block per response row with pattern rows", async () => {
    getPatterns.mockResolvedValue({
      generated_at_seconds: 1,
      scenarios: [
        {
          scenario_id: "SC-PP-008",
          total_decided_cases: 4,
          patterns: [
            {
              decision_kind: "reject",
              fact_ontology_type: "SanctionsProximity",
              case_count: 3,
              share_of_decisions: 75.0,
              share_of_decision_kind: 100.0,
              sample_fact_ids: ["SUP-001-PROX", "SUP-007-PROX"],
            },
            {
              decision_kind: "approve",
              fact_ontology_type: "Product",
              case_count: 1,
              share_of_decisions: 25.0,
              share_of_decision_kind: 100.0,
              sample_fact_ids: ["P-EL-9001"],
            },
          ],
        },
      ],
    });

    render(<InsightsModal onClose={vi.fn()} />);

    expect(await screen.findByText("SC-PP-008")).toBeInTheDocument();
    expect(screen.getByText("4 decided cases")).toBeInTheDocument();
    expect(screen.getByText("SanctionsProximity")).toBeInTheDocument();
    expect(screen.getByText("Product")).toBeInTheDocument();
    // Percentages rendered — there are duplicates per scenario, just confirm presence
    expect(screen.getAllByText("100%").length).toBeGreaterThan(0);
    expect(screen.getByText("75%")).toBeInTheDocument();
    // Sample fact ids surface in the row
    expect(screen.getByText(/SUP-001-PROX, SUP-007-PROX/)).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    getPatterns.mockResolvedValue({ generated_at_seconds: 1, scenarios: [] });
    const onClose = vi.fn();
    render(<InsightsModal onClose={onClose} />);
    await screen.findByText(/No reviewer signal yet/i);
    await userEvent.setup().keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("surfaces fetch errors instead of looping on loading", async () => {
    getPatterns.mockRejectedValue(new Error("403 admin only"));
    render(<InsightsModal onClose={vi.fn()} />);
    expect(await screen.findByText(/403 admin only/i)).toBeInTheDocument();
  });
});
