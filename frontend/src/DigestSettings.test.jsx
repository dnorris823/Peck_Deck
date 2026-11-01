// Settings > Notifications: the evening push and weekly email digests, and the
// time zone the first visit to Settings sets from the browser.
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
import { SettingsPage, browserTimeZone } from "./UsersSettings.jsx";

beforeEach(() => {
  vi.clearAllMocks();
  prefs = {
    quiet_interval_seconds: 60, notify_new_species_only: false,
    notify_first_ever: true, notify_first_at_feeder: true, notify_first_this_year: true,
    animal_alerts: {}, animal_quiet_interval_seconds: 1800,
    time_zone: "America/Chicago", digest_push: false, digest_push_time: "19:00", digest_email: false,
  };
  savePreferences.mockImplementation(async (p) => ({ ...prefs, ...p }));
});

function openDigests() {
  render(<SettingsPage />);
  fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
  return screen.getByRole("group", { name: "Digests" });
}

describe("digests in Settings", () => {
  it("shows both digests off by default", () => {
    const group = openDigests();
    expect(within(group).getByText("Evening push")).toBeInTheDocument();
    expect(within(group).getByText("Weekly email")).toBeInTheDocument();
    const toggles = within(group).getAllByRole("button");
    expect(toggles.map(t => t.getAttribute("aria-pressed"))).toEqual(["false", "false"]);
    expect(within(group).getByLabelText("Evening push time")).toBeDisabled();
    expect(screen.getByText(/Times use America\/Chicago/)).toBeInTheDocument();
  });

  it("saves each switch on its own", async () => {
    const group = openDigests();
    fireEvent.click(within(group).getAllByRole("button")[1]);
    await waitFor(() => expect(savePreferences).toHaveBeenCalledWith({ digest_email: true }));
  });

  it("saves the push time when the field loses focus", async () => {
    prefs.digest_push = true;
    const group = openDigests();
    const input = within(group).getByLabelText("Evening push time");
    fireEvent.change(input, { target: { value: "20:30" } });
    expect(savePreferences).not.toHaveBeenCalled();
    fireEvent.blur(input);
    await waitFor(() => expect(savePreferences).toHaveBeenCalledWith({ digest_push_time: "20:30" }));
  });

  it("sets the time zone from the browser when none is stored", async () => {
    prefs.time_zone = null;
    render(<SettingsPage />);
    await waitFor(() => expect(savePreferences).toHaveBeenCalledWith({ time_zone: browserTimeZone() }));
  });

  it("leaves a stored time zone alone", () => {
    render(<SettingsPage />);
    expect(savePreferences).not.toHaveBeenCalled();
  });
});
