/**
 * ScenarioEditModal — the save-flow behaviour from the Phase 1 audit
 * fixes:
 *   - Footer renders "Currently v{N} · Saving creates v{N+1}"
 *   - Save uses the server's authoritative version number in the alert
 *   - The "preserved as v{N-1}" line is suppressed when newVersion === 1
 *   - The Version history button mounts the ScenarioVersionsModal
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ScenarioEditModal } from "../ScenarioEditModal";
import * as api from "../../api";

vi.mock("../../api", () => ({
  getScenario: vi.fn(),
  editScenario: vi.fn(),
  deleteScenario: vi.fn(),
  listScenarioVersions: vi.fn().mockResolvedValue([]),
  getScenarioFull: vi.fn(),
}));

const getScenario = api.getScenario as ReturnType<typeof vi.fn>;
const editScenario = api.editScenario as ReturnType<typeof vi.fn>;

const baseScenario = {
  id: "SC-PP-008",
  title: "Supplier onboarding",
  domain: "Planning & Procurement",
  autonomous: false,
  version: 3,
  match_keywords: ["supplier"],
  interpreted_as: "onboard new supplier",
  clarifying_question: "Confirm onboarding?",
  suggested_prompt: "Onboard supplier",
  action_type: "supplier_onboarding_review",
  is_builtin: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  getScenario.mockResolvedValue(baseScenario);
  // Stub window.alert — jsdom doesn't implement it by default and the
  // save handler calls it.
  vi.stubGlobal("alert", vi.fn());
});

describe("ScenarioEditModal", () => {
  it("renders 'Currently v3 · Saving creates v4' in the footer", async () => {
    render(
      <ScenarioEditModal scenarioId="SC-PP-008" onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    expect(await screen.findByText(/Currently/)).toBeInTheDocument();
    expect(screen.getByText(/v3/)).toBeInTheDocument();
    expect(screen.getByText(/Saving creates v4/i)).toBeInTheDocument();
  });

  it("uses the server's version in the save alert (not a client-side guess)", async () => {
    // Local view thinks current is v3, so the client-side guess would
    // say "Saved as v4." The server has actually moved to v9 (another
    // concurrent edit). The alert must surface v9, not v4.
    editScenario.mockResolvedValue({ scenario_id: "SC-PP-008", updated: 1, version: 9 });

    render(
      <ScenarioEditModal scenarioId="SC-PP-008" onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    await screen.findByDisplayValue("Supplier onboarding");
    await userEvent.setup().click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() => {
      expect(window.alert).toHaveBeenCalledWith(
        expect.stringMatching(/Saved as v9\. The prior content is preserved as v8\./),
      );
    });
  });

  it("suppresses the 'preserved as v0' line when newVersion === 1", async () => {
    editScenario.mockResolvedValue({ scenario_id: "SC-PP-008", updated: 1, version: 1 });

    render(
      <ScenarioEditModal scenarioId="SC-PP-008" onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    await screen.findByDisplayValue("Supplier onboarding");
    await userEvent.setup().click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() => {
      expect(window.alert).toHaveBeenCalledTimes(1);
    });
    const message = (window.alert as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(message).toBe("Saved as v1.");
    expect(message).not.toMatch(/preserved as v0/);
  });

  it("opens the version-history modal when the link is clicked", async () => {
    render(
      <ScenarioEditModal scenarioId="SC-PP-008" onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    await screen.findByText(/Currently/);
    await userEvent.setup().click(screen.getByRole("button", { name: /Version history/i }));
    expect(
      await screen.findByText(/Version history · SC-PP-008/i),
    ).toBeInTheDocument();
  });
});
