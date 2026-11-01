// Settings > Notifications: the three new species switches and "Only new species".
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

const patch = vi.fn();
let prefs;
vi.mock("./DataContext.jsx", () => ({
  useData: () => ({
    data: { ME: { id: 1, name: "Owner", email: "o@x.dev", notify_email: true, role: "owner" }, PREFERENCES: prefs },
    patch,
  }),
}));
vi.mock("./Appearance.jsx", () => ({ useAppearance: () => ({ appearance: {}, update: vi.fn() }) }));
vi.mock("./push.js", () => ({
  currentSubscription: vi.fn().mockResolvedValue(null), disablePush: vi.fn(), enablePush: vi.fn(),
  fetchPushConfig: vi.fn().mockResolvedValue({ enabled: false }), permission: () => "default",
  pushSupported: () => false,
}));
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  savePreferences: vi.fn(),
}));

import { savePreferences } from "./data.js";
import { SettingsPage } from "./UsersSettings.jsx";

beforeEach(() => {
  vi.clearAllMocks();
  prefs = {
    quiet_interval_seconds: 60, notify_new_species_only: false,
    notify_first_ever: true, notify_first_at_feeder: true, notify_first_this_year: false,
    animal_alerts: {}, animal_quiet_interval_seconds: 1800,
  };
  savePreferences.mockImplementation(async (p) => ({ ...prefs, ...p }));
});

function openNotifications() {
  render(<SettingsPage />);
  fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
  return screen.getByRole("group", { name: "New species alerts" });
}

describe("new species alerts in Settings", () => {
  it("shows the three kinds with the user's settings", () => {
    const group = openNotifications();
    expect(within(group).getByText("First ever")).toBeInTheDocument();
    expect(within(group).getByText("First at this feeder")).toBeInTheDocument();
    expect(within(group).getByText("First this year")).toBeInTheDocument();
    const rows = within(group).getAllByRole("button");
    expect(rows.map(r => r.getAttribute("aria-pressed"))).toEqual(["true", "true", "false"]);
  });

  it("treats a missing switch as on", () => {
    delete prefs.notify_first_ever;
    const group = openNotifications();
    expect(within(group).getAllByRole("button")[0]).toHaveAttribute("aria-pressed", "true");
  });

  it("saves one kind at a time", async () => {
    const group = openNotifications();
    fireEvent.click(within(group).getAllByRole("button")[2]);
    await waitFor(() => expect(savePreferences).toHaveBeenCalledWith({ notify_first_this_year: true }));
  });

  it("renames the old switch to Only new species", () => {
    openNotifications();
    expect(screen.getByText("Only new species")).toBeInTheDocument();
    expect(screen.queryByText("Notify only for new species")).not.toBeInTheDocument();
  });
});
