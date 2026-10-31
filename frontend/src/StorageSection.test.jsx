// Settings > Storage: the database and image sizes, and the retention rule.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchStorage: vi.fn(),
}));
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: {}, patch: vi.fn() }) }));

import { StorageSection } from "./UsersSettings.jsx";
import { fetchStorage, formatBytes } from "./data.js";

describe("formatBytes", () => {
  it("keeps small counts in bytes and scales the rest by 1024", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(252337175)).toBe("240.6 MB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB");
  });
});

describe("StorageSection", () => {
  beforeEach(() => { fetchStorage.mockReset(); });

  it("shows both sizes and says retention is off", async () => {
    fetchStorage.mockResolvedValue({
      database_bytes: 252337175, image_bytes: 218336211, retention_unknown_days: 0,
    });

    render(<StorageSection />);

    expect(await screen.findByText("240.6 MB")).toBeInTheDocument();
    expect(screen.getByText("208.2 MB")).toBeInTheDocument();
    expect(screen.getByText("Off. Nothing is deleted.")).toBeInTheDocument();
  });

  it("names the age when retention is on", async () => {
    fetchStorage.mockResolvedValue({
      database_bytes: 2048, image_bytes: 1024, retention_unknown_days: 30,
    });

    render(<StorageSection />);

    expect(
      await screen.findByText("Unknown sightings older than 30 days are deleted daily."),
    ).toBeInTheDocument();
  });

  it("says so when the sizes fail to load", async () => {
    fetchStorage.mockRejectedValue(new Error("Request failed (500)"));

    render(<StorageSection />);

    expect(await screen.findByText(/Couldn't load storage sizes/)).toBeInTheDocument();
  });
});
