// Settings > Notifications: the per-group animal push switches and interval.
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
    animal_alerts: { squirrel: true, raccoon: true, bear: true, cat: true, chipmunk: false,
                     rat: false, rabbit: false, opossum: false, deer: false },
    animal_quiet_interval_seconds: 1800,
  };
  savePreferences.mockImplementation(async (p) => ({ ...prefs, ...p }));
});

function openNotifications() {
  render(<SettingsPage />);
  fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
  return screen.getByRole("group", { name: "Animal alerts" });
}

describe("animal alerts in Settings", () => {
  it("shows a switch per group with the user's settings", () => {
    const group = openNotifications();
    const rows = within(group).getAllByRole("button");
    expect(rows).toHaveLength(9);
    expect(rows[0]).toHaveAttribute("aria-pressed", "true");   // squirrel
    expect(rows[4]).toHaveAttribute("aria-pressed", "false");  // chipmunk
  });

  it("saves one group at a time", async () => {
    const group = openNotifications();
    fireEvent.click(within(group).getAllByRole("button")[4]);
    await waitFor(() => expect(savePreferences).toHaveBeenCalledWith({ animal_alerts: { chipmunk: true } }));
  });

  it("saves the interval", async () => {
    openNotifications();
    fireEvent.change(screen.getByLabelText("Interval"), { target: { value: "3600" } });
    await waitFor(() => expect(savePreferences).toHaveBeenCalledWith({ animal_quiet_interval_seconds: 3600 }));
  });
});
