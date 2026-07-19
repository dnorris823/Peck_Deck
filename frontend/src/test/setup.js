// Vitest global setup — runs before each test file.
// Adds jest-dom's DOM matchers (toBeInTheDocument, toHaveTextContent, …) and
// clears localStorage between tests so token/appearance state never leaks.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  localStorage.clear();
});
