// Feeders page: each card's tier counts and the Tier 2 warning beside them,
// and the settings dialog that shares, edits, hands over and removes a feeder.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

let mockData;
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData, reload: vi.fn() }) }));
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchFeederAccess: vi.fn(),
  addFeederMember: vi.fn(),
  removeFeederMember: vi.fn(),
  updateDevice: vi.fn(),
  deleteDevice: vi.fn(),
  fetchDeviceToken: vi.fn(),
  rotateDeviceToken: vi.fn(),
  countSightingsBefore: vi.fn(),
  deleteSightingsBefore: vi.fn(),
}));

import { DevicesPage, Power, tierMixText } from "./Devices.jsx";
import {
  addFeederMember, countSightingsBefore, deleteDevice, deleteSightingsBefore, fetchDeviceToken,
  fetchFeederAccess, removeFeederMember, rotateDeviceToken, updateDevice,
} from "./data.js";

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

describe("Power", () => {
  it("shows a mains feeder as plugged in, with no battery bar", () => {
    const { container } = render(<Power source="mains" battery={0.78} />);
    expect(screen.getByText("Mains power")).toBeInTheDocument();
    expect(container.querySelector(".bat-bar")).toBeNull();
  });

  it("shows a battery feeder's level", () => {
    const { container } = render(<Power source="battery" battery={0.15} />);
    expect(screen.getByText("15%")).toBeInTheDocument();
    expect(container.querySelector(".bat-crit")).not.toBeNull();
  });

  it("says Battery when a battery feeder reports no level", () => {
    render(<Power source="battery" battery={null} />);
    expect(screen.getByText("Battery")).toBeInTheDocument();
  });

  it("shows nothing for a Pi that does not report its power source", () => {
    // A stale level from seed data must not draw a bar.
    const { container } = render(<Power source={null} battery={0.78} />);
    expect(container).toBeEmptyDOMElement();
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

describe("Feeder settings", () => {
  const owner = { id: 1, name: "Dominic Norris", email: "dom@peck.deck", notify_email: true };
  const brother = { id: 2, name: "Sam Norris", email: "sam@peck.deck", notify_email: false };
  const dad = { id: 3, name: "Pat Norris", email: "pat@peck.deck", notify_email: true };

  function openFeeder(me, d = { ...feeder(7, "Maple", null), ownerId: 1, city: "Stowe", state: "VT" }) {
    mockData = {
      SIGHTINGS: [], DEVICES: [d], ME: me,
      USERS: me.role === "owner"
        ? [owner, brother, dad].map(u => ({ ...u, role: "viewer", av: "XX", avBg: "#000" }))
        : [],
    };
    render(<DevicesPage />);
    fireEvent.click(screen.getByRole("button", { name: /Maple/ }));
    return screen.getByRole("dialog", { name: "Maple settings" });
  }

  beforeEach(() => {
    vi.mocked(fetchFeederAccess).mockReset();
    vi.mocked(addFeederMember).mockReset();
    vi.mocked(removeFeederMember).mockReset();
    vi.mocked(updateDevice).mockReset();
    vi.mocked(deleteDevice).mockReset();
    vi.mocked(fetchDeviceToken).mockReset();
    vi.mocked(rotateDeviceToken).mockReset();
    vi.mocked(countSightingsBefore).mockReset();
    vi.mocked(deleteSightingsBefore).mockReset();
  });

  it("lists the owner and members as recipients, not every user with email on", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [brother] });
    const dialog = openFeeder({ id: 1, role: "owner" });
    await within(dialog).findByText("Sam Norris", { selector: "div" });
    expect(within(dialog).getByText("Dominic Norris", { selector: "div" })).toBeInTheDocument();
    // Pat has email alerts on but is not on this feeder.
    expect(within(dialog).queryByText("Pat Norris", { selector: "div" })).toBeNull();
    expect(fetchFeederAccess).toHaveBeenCalledWith(7);
  });

  it("shares by email and removes a member", async () => {
    vi.mocked(fetchFeederAccess)
      .mockResolvedValueOnce({ owner, members: [] })
      .mockResolvedValueOnce({ owner, members: [dad] })
      .mockResolvedValueOnce({ owner, members: [] });
    const dialog = openFeeder({ id: 1, role: "owner" });
    await within(dialog).findByText("Dominic Norris", { selector: "div" });

    fireEvent.change(within(dialog).getByLabelText("Share with"), { target: { value: " pat@peck.deck " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    await within(dialog).findByText("Pat Norris", { selector: "div" });
    expect(addFeederMember).toHaveBeenCalledWith(7, { email: "pat@peck.deck" });

    fireEvent.click(within(dialog).getByRole("button", { name: "Remove Pat Norris" }));
    await waitFor(() => expect(within(dialog).queryByText("Pat Norris", { selector: "div" })).toBeNull());
    expect(removeFeederMember).toHaveBeenCalledWith(7, 3);
  });

  it("shows the server's refusal when the email has no account", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(addFeederMember).mockRejectedValue(new Error("No user has that email."));
    const dialog = openFeeder({ id: 1, role: "owner" });
    await within(dialog).findByText("Dominic Norris", { selector: "div" });
    fireEvent.change(within(dialog).getByLabelText("Share with"), { target: { value: "x@y.z" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("No user has that email.");
  });

  it("saves the location, sending an empty field to clear it", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(updateDevice).mockResolvedValue({});
    const dialog = openFeeder({ id: 1, role: "owner" });
    fireEvent.change(within(dialog).getByLabelText("City"), { target: { value: " Burlington " } });
    fireEvent.change(within(dialog).getByLabelText("State"), { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save details" }));
    await within(dialog).findByText("Saved.");
    expect(updateDevice).toHaveBeenCalledWith(7, {
      name: "Maple", city: "Burlington", state: "", feed_type: "",
    });
  });

  it("lets a viewer who owns the feeder manage it", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner: brother, members: [] });
    const dialog = openFeeder({ id: 2, role: "viewer" },
      { ...feeder(7, "Maple", null), ownerId: 2 });
    await within(dialog).findByText("Sam Norris", { selector: "div" });
    expect(within(dialog).getByLabelText("Share with")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Remove feeder…" })).toBeInTheDocument();
    // A viewer cannot list users, so there is no one to hand the feeder to.
    expect(within(dialog).queryByLabelText("Owned by")).toBeNull();
  });

  it("removes a feeder with sightings only after its name is typed", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(deleteDevice).mockResolvedValue(null);
    const dialog = openFeeder({ id: 1, role: "owner" },
      { ...feeder(7, "Maple", null), ownerId: 1, allTime: 4252 });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove feeder…" }));
    expect(within(dialog).getByText(/its 4,252 sightings/)).toBeInTheDocument();

    const remove = within(dialog).getByRole("button", { name: "Remove Maple" });
    expect(remove).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Type Maple to confirm"), { target: { value: "Mapl" } });
    expect(remove).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Type Maple to confirm"), { target: { value: "Maple" } });
    fireEvent.click(remove);
    await waitFor(() => expect(deleteDevice).toHaveBeenCalledWith(7, { withSightings: true }));
  });

  it("removes an empty feeder without asking for its sightings to go", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(deleteDevice).mockResolvedValue(null);
    const dialog = openFeeder({ id: 1, role: "owner" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove feeder…" }));
    expect(within(dialog).queryByLabelText("Type Maple to confirm")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove Maple" }));
    await waitFor(() => expect(deleteDevice).toHaveBeenCalledWith(7, { withSightings: false }));
  });

  it("shows the server's refusal when a removal fails", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(deleteDevice).mockRejectedValue(new Error("Device has 3 sightings."));
    const dialog = openFeeder({ id: 1, role: "owner" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove feeder…" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove Maple" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Device has 3 sightings.");
  });

  it("rotates the token only after a confirm, and shows the new one", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(rotateDeviceToken).mockResolvedValue({ id: 7, token: "new-token-abc" });
    const dialog = openFeeder({ id: 1, role: "owner" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rotate token…" }));
    expect(rotateDeviceToken).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Rotate token" }));
    expect(await within(dialog).findByText("new-token-abc")).toBeInTheDocument();
    expect(rotateDeviceToken).toHaveBeenCalledWith(7);
  });

  it("shows the current token on request", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(fetchDeviceToken).mockResolvedValue({ id: 7, token: "current-token" });
    const dialog = openFeeder({ id: 1, role: "owner" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Show token" }));
    expect(await within(dialog).findByText("current-token")).toBeInTheDocument();
  });

  it("counts the sightings before a date, then deletes them on confirm", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(countSightingsBefore).mockResolvedValue({ count: 4388 });
    vi.mocked(deleteSightingsBefore).mockResolvedValue(null);
    const dialog = openFeeder({ id: 1, role: "owner" },
      { ...feeder(7, "Maple", null), ownerId: 1, allTime: 4397 });

    fireEvent.change(within(dialog).getByLabelText("Delete sightings before"),
      { target: { value: "2026-10-28" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Check" }));
    const confirm = await within(dialog).findByRole("button", { name: "Delete 4,388 sightings" });
    // Local midnight on the picked day.
    expect(countSightingsBefore).toHaveBeenCalledWith(7, new Date(2026, 9, 28));
    expect(deleteSightingsBefore).not.toHaveBeenCalled();

    fireEvent.click(confirm);
    expect(await within(dialog).findByText("Deleted 4,388 sightings.")).toBeInTheDocument();
    expect(deleteSightingsBefore).toHaveBeenCalledWith(7, new Date(2026, 9, 28));
  });

  it("says so when no sightings are older than the date", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(countSightingsBefore).mockResolvedValue({ count: 0 });
    const dialog = openFeeder({ id: 1, role: "owner" },
      { ...feeder(7, "Maple", null), ownerId: 1, allTime: 3 });
    fireEvent.change(within(dialog).getByLabelText("Delete sightings before"),
      { target: { value: "2020-01-01" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Check" }));
    expect(await within(dialog).findByText("No sightings before that day.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /^Delete .* sightings$/ })).toBeNull();
  });

  it("hides the date delete for a feeder with no sightings", () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    const dialog = openFeeder({ id: 1, role: "owner" });
    expect(within(dialog).queryByLabelText("Delete sightings before")).toBeNull();
  });

  it("hands the feeder to another user", async () => {
    vi.mocked(fetchFeederAccess).mockResolvedValue({ owner, members: [] });
    vi.mocked(updateDevice).mockResolvedValue({});
    const dialog = openFeeder({ id: 1, role: "owner" });
    fireEvent.change(within(dialog).getByLabelText("Owned by"), { target: { value: "3" } });
    expect(within(dialog).getByText(/Dominic Norris stays on as a member/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Make Pat Norris the owner" }));
    await waitFor(() => expect(updateDevice).toHaveBeenCalledWith(7, { owner_id: 3 }));
  });

  it("gives a member no controls and asks for no member list", () => {
    const dialog = openFeeder({ id: 2, role: "viewer" });
    expect(within(dialog).getByText(/Only its owner can change/)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Share with")).toBeNull();
    expect(fetchFeederAccess).not.toHaveBeenCalled();
  });
});
