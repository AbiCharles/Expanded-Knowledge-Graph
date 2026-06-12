/**
 * CaseSpecModal — the version-pinning behaviour from Phase 1:
 *   - "Ran against v{N}" pill appears when the case has scenario_version
 *   - Fetch routes to the historical snapshot (?version=N) when set
 *   - Falls back to the live (?full=1) when the case predates versioning
 *   - Esc closes the modal
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { CaseSpecModal } from "../CaseSpecModal";
import * as api from "../../api";
import type { CaseFull } from "../../types";

vi.mock("../../api", () => ({
  getScenarioFull: vi.fn(),
  getOntologyClasses: vi.fn().mockResolvedValue([]),
  getMappings: vi.fn().mockResolvedValue({ ontology_id: "tcs_core", mappings: {} }),
  getCaseHighlights: vi.fn().mockResolvedValue({
    case_id: "C-001",
    scenario_id: "SC-PP-008",
    scenario_version: 3,
    decision_kind: null,
    highlighted_fact_refs: [],
  }),
}));

const getFull = api.getScenarioFull as ReturnType<typeof vi.fn>;

function makeCase(overrides: Partial<CaseFull> = {}): CaseFull {
  return {
    case_id: "C-001",
    scenario_id: "SC-PP-008",
    scenario_version: 3,
    phase: "review",
    actor: null,
    lineage: [],
    stages: [],
    scenario: { title: "Supplier onboarding" } as any,
    ...overrides,
  } as CaseFull;
}

beforeEach(() => {
  vi.clearAllMocks();
  getFull.mockResolvedValue({
    id: "SC-PP-008",
    title: "Supplier onboarding",
    domain: "Planning & Procurement",
    stages: {},
    match_keywords: ["supplier"],
    interpreted_as: "onboard new supplier",
    is_builtin: true,
  });
});

describe("CaseSpecModal", () => {
  it("renders the 'Ran against v{N}' pill when the case has scenario_version", async () => {
    render(<CaseSpecModal active={makeCase({ scenario_version: 3 })} onClose={vi.fn()} />);
    expect(await screen.findByText(/Ran against v3/i)).toBeInTheDocument();
  });

  it("omits the version pill when scenario_version is null (pre-versioning case)", async () => {
    render(<CaseSpecModal active={makeCase({ scenario_version: null })} onClose={vi.fn()} />);
    await waitFor(() => expect(getFull).toHaveBeenCalled());
    expect(screen.queryByText(/Ran against v/i)).not.toBeInTheDocument();
  });

  it("fetches the historical snapshot when scenario_version is set", async () => {
    render(<CaseSpecModal active={makeCase({ scenario_version: 2 })} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(getFull).toHaveBeenCalledWith("SC-PP-008", { version: 2 });
    });
  });

  it("fetches the live spec (no version) when scenario_version is null", async () => {
    render(<CaseSpecModal active={makeCase({ scenario_version: null })} onClose={vi.fn()} />);
    await waitFor(() => {
      expect(getFull).toHaveBeenCalledWith("SC-PP-008", {});
    });
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(<CaseSpecModal active={makeCase()} onClose={onClose} />);
    await screen.findByText(/Ran against v3/i);
    await userEvent.setup().keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
