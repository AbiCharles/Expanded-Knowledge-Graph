/**
 * ScenarioVersionsModal — list rendering, empty state, and the
 * stale-content-clear behaviour from the code-review fix.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { ScenarioVersionsModal } from "../ScenarioVersionsModal";
import * as api from "../../api";

vi.mock("../../api", () => ({
  listScenarioVersions: vi.fn(),
  getScenarioFull: vi.fn(),
}));

const listVersions = api.listScenarioVersions as ReturnType<typeof vi.fn>;
const getFull = api.getScenarioFull as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ScenarioVersionsModal", () => {
  it("renders the version list newest-first", async () => {
    listVersions.mockResolvedValue([
      { version: 3, saved_at: 1_780_000_000, title: "Newer title" },
      { version: 2, saved_at: 1_770_000_000, title: "Middle title" },
      { version: 1, saved_at: 1_760_000_000, title: "Original" },
    ]);

    render(<ScenarioVersionsModal scenarioId="SC-PP-008" onClose={vi.fn()} />);

    expect(await screen.findByText("v3")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getByText("Newer title")).toBeInTheDocument();
    expect(screen.getByText("3 saved versions")).toBeInTheDocument();
  });

  it("shows the empty-state hint when no versions exist", async () => {
    listVersions.mockResolvedValue([]);

    render(<ScenarioVersionsModal scenarioId="SC-AUTO-EPHEMERAL" onClose={vi.fn()} />);

    expect(
      await screen.findByText(/hasn't been persisted to disk/i),
    ).toBeInTheDocument();
  });

  it("clears the prior version's body before the new fetch resolves (fix #5)", async () => {
    listVersions.mockResolvedValue([
      { version: 2, saved_at: 1_770_000_000, title: "v2 title" },
      { version: 1, saved_at: 1_760_000_000, title: "v1 title" },
    ]);

    // v2 fetch resolves immediately; v1 fetch we control manually so we
    // can observe the in-flight state.
    let resolveV1!: (d: unknown) => void;
    const v1Promise = new Promise((resolve) => {
      resolveV1 = resolve;
    });
    getFull.mockImplementation((_id: string, opts: { version?: number }) => {
      if (opts.version === 2) return Promise.resolve({ title: "v2 content", version: 2 });
      if (opts.version === 1) return v1Promise;
      return Promise.resolve(null);
    });

    const user = userEvent.setup();
    render(<ScenarioVersionsModal scenarioId="SC-PP-008" onClose={vi.fn()} />);

    // Click v2 → its content loads.
    const v2Btn = await screen.findByRole("button", { name: /v2.*v2 title/i });
    await user.click(v2Btn);
    await waitFor(() =>
      expect(screen.getByText(/"title": "v2 content"/i)).toBeInTheDocument(),
    );

    // Click v1 → v2 content must DISAPPEAR before v1 resolves.
    const v1Btn = screen.getByRole("button", { name: /v1.*v1 title/i });
    await user.click(v1Btn);

    await waitFor(() => {
      expect(screen.queryByText(/"title": "v2 content"/i)).not.toBeInTheDocument();
      expect(screen.getByText(/Loading v1…/i)).toBeInTheDocument();
    });

    // Resolve v1 → its content should appear.
    resolveV1({ title: "v1 content", version: 1 });
    await waitFor(() =>
      expect(screen.getByText(/"title": "v1 content"/i)).toBeInTheDocument(),
    );
  });

  it("calls onClose when the backdrop is clicked", async () => {
    listVersions.mockResolvedValue([]);
    const onClose = vi.fn();
    const { container } = render(
      <ScenarioVersionsModal scenarioId="SC-PP-008" onClose={onClose} />,
    );
    await screen.findByText(/hasn't been persisted to disk/i);
    const backdrop = container.querySelector(".modal-backdrop");
    expect(backdrop).not.toBeNull();
    await userEvent.setup().click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
