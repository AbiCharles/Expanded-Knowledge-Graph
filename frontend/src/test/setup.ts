import "@testing-library/jest-dom";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// RTL doesn't auto-cleanup with Vitest's globals; unmount between tests
// so a stray modal doesn't bleed into the next test's queries.
afterEach(() => {
  cleanup();
});
