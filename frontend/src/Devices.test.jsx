// Feeders page: each card's tier counts and the Tier 2 warning beside them.
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

let mockData;
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData, reload: vi.fn() }) }));

import { DevicesPage, tierMixText } from "./Devices.jsx";

const mix = (counts, more = {}) => ({
  hours: 24, counts: { gpu: 0, local: 0, cloud: 0, none: 0, ...counts },
  tier2Asked: 0, tier2Missed: 0, tier2Down: false, ...more,
});

const feeder = (id, name, tierMix) => ({
  id, name, city: "—", state: "", feed: "—", status: "online", battery: null,
  lastSeen: "9s ago", todaySightings: 0, weekSightings: 0, allTime: 0, tierMix,
});

describe("tierMixText", () => {
  it("names the tiers the way the app shows them", () => {
    expect(tierMixText(mix({ gpu: 41, local: 3 }))).toBe("Last 24 h: 41 GPU, 3 Pi, 0 none");
  });

  it("adds Claude only once it has answered", () => {
    expect(tierMixText(mix({ gpu: 2, cloud: 1, none: 1 }))).toBe("Last 24 h: 2 GPU, 0 Pi, 1 Claude, 1 none");
  });
});

describe("Feeders", () => {
  it("shows each feeder's counts, and the warning only where Tier 2 is down", () => {
    mockData = {
      SIGHTINGS: [],
      USERS: [],
      DEVICES: [
        feeder(1, "Maple", mix({ gpu: 41, local: 3 }, { tier2Asked: 44, tier2Missed: 1 })),
        feeder(2, "Porch", mix({ local: 9, none: 1 }, { tier2Asked: 10, tier2Missed: 10, tier2Down: true })),
      ],
    };
    render(<DevicesPage />);
    expect(screen.getByText("Last 24 h: 41 GPU, 3 Pi, 0 none")).toBeInTheDocument();
    expect(screen.getByText("Last 24 h: 0 GPU, 9 Pi, 1 none")).toBeInTheDocument();
    const warnings = screen.getAllByText("GPU not answering");
    expect(warnings).toHaveLength(1);
    expect(warnings[0].closest(".station-card")).toHaveTextContent("Porch");
    expect(warnings[0]).toHaveAttribute("title", "10 of 10 captures got no answer from the GPU server.");
  });
});
