/**
 * Phase 3b — promote flow tests for InsightsModal.
 *
 * Covers:
 *   - Promote button per row opens the confirmation modal
 *   - Confirm calls api.promotePattern with the right shape
 *   - Promote success refreshes the patterns list (reload)
 *   - Cancel dismisses the modal without calling the API
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { InsightsModal } from "../InsightsModal";
import * as api from "../../api";

vi.mock("../../api", () => ({
  getInsightsPatterns: vi.fn(),
  promotePattern: vi.fn(),
}));

const getPatterns = api.getInsightsPatterns as ReturnType<typeof vi.fn>;
const promote = api.promotePattern as ReturnType<typeof vi.fn>;

const SAMPLE = {
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
          share_of_decisions: 75,
          share_of_decision_kind: 100,
          sample_fact_ids: ["SUP-001-PROX"],
        },
      ],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  getPatterns.mockResolvedValue(SAMPLE);
  vi.stubGlobal("alert", vi.fn());
});

describe("InsightsModal — promote", () => {
  it("clicking Promote opens the confirmation modal", async () => {
    render(<InsightsModal onClose={vi.fn()} />);
    await screen.findByText("SanctionsProximity");
    await userEvent.setup().click(screen.getByRole("button", { name: /Promote →/i }));
    expect(await screen.findByText(/Promote this driver to a scenario rule/i))
      .toBeInTheDocument();
  });

  it("Cancel dismisses without calling the API", async () => {
    render(<InsightsModal onClose={vi.fn()} />);
    const user = userEvent.setup();
    await screen.findByText("SanctionsProximity");
    await user.click(screen.getByRole("button", { name: /Promote →/i }));
    await screen.findByText(/Promote this driver/i);
    await user.click(screen.getByRole("button", { name: /Cancel/i }));
    await waitFor(() =>
      expect(screen.queryByText(/Promote this driver/i)).not.toBeInTheDocument(),
    );
    expect(promote).not.toHaveBeenCalled();
  });

  it("Promote pattern submits with the right shape and reloads", async () => {
    promote.mockResolvedValue({
      scenario_id: "SC-PP-008",
      version: 2,
      pattern_id: "auto-abc",
      replaced: false,
      stats: { case_count: 3, decisions_of_kind: 3, decisions_total: 4, share_of_kind_pct: 100 },
    });
    render(<InsightsModal onClose={vi.fn()} />);
    const user = userEvent.setup();
    await screen.findByText("SanctionsProximity");
    await user.click(screen.getByRole("button", { name: /Promote →/i }));
    await user.click(screen.getByRole("button", { name: /Promote pattern/i }));

    await waitFor(() => {
      expect(promote).toHaveBeenCalledWith({
        scenario_id: "SC-PP-008",
        decision_kind: "reject",
        fact_ontology_type: "SanctionsProximity",
      });
    });
    // The success path calls alert() and then re-fetches patterns.
    await waitFor(() => {
      expect(window.alert).toHaveBeenCalled();
      // Initial load + reload after promote.
      expect(getPatterns).toHaveBeenCalledTimes(2);
    });
  });

  it("Promote failure surfaces the server's error and keeps the modal open", async () => {
    promote.mockRejectedValue(new Error("guardrail: case_count=1 < min_case_count=2"));
    render(<InsightsModal onClose={vi.fn()} />);
    const user = userEvent.setup();
    await screen.findByText("SanctionsProximity");
    await user.click(screen.getByRole("button", { name: /Promote →/i }));
    await user.click(screen.getByRole("button", { name: /Promote pattern/i }));
    expect(await screen.findByText(/guardrail: case_count/i)).toBeInTheDocument();
    // Modal stays open so the admin can read the error.
    expect(screen.getByText(/Promote this driver to a scenario rule/i)).toBeInTheDocument();
  });
});
