// Users page: the owner controls in each user's Manage dialog.
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

let mockData;
const reload = vi.fn(async () => {});
vi.mock("./DataContext.jsx", () => ({ useData: () => ({ data: mockData, reload }) }));
vi.mock("./data.js", async (importOriginal) => ({
  ...(await importOriginal()),
  fetchFeederAccess: vi.fn(),
  addFeederMember: vi.fn(),
  removeFeederMember: vi.fn(),
  updateUser: vi.fn(),
  setUserRole: vi.fn(),
  changePassword: vi.fn(),
  signOutUser: vi.fn(),
  deleteUser: vi.fn(),
}));

import { UsersPage } from "./Users.jsx";
import {
  addFeederMember, changePassword, deleteUser, fetchFeederAccess, removeFeederMember,
  setUserRole, signOutUser, updateUser,
} from "./data.js";

const me = { id: 1, name: "Dominic Norris", email: "dom@peck.deck", role: "owner", notify_email: true };
const sam = { id: 2, name: "Sam Norris", email: "sam@peck.deck", role: "viewer", notify_email: true };
const row = u => ({ ...u, av: "XX", avBg: "#000" });

function manage(user) {
  mockData = {
    ME: me,
    USERS: [row(me), row(sam)],
    DEVICES: [{ id: 7, name: "Maple", ownerId: 1 }, { id: 8, name: "Porch", ownerId: 1 }],
  };
  vi.mocked(fetchFeederAccess).mockImplementation(async (id) => ({
    owner: me, members: id === 7 ? [sam] : [],
  }));
  render(<UsersPage />);
  const rowEl = screen.getByText(user.name, { exact: false }).closest(".user-row");
  fireEvent.click(within(rowEl).getByRole("button", { name: "Manage" }));
  return screen.getByRole("dialog");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Users page", () => {
  it("shows one checkbox per feeder and toggles membership", async () => {
    const dialog = manage(sam);
    const maple = await within(dialog).findByRole("checkbox", { name: /^Maple/ });
    const porch = within(dialog).getByRole("checkbox", { name: /^Porch/ });
    expect(maple).toBeChecked();
    expect(porch).not.toBeChecked();

    fireEvent.click(porch);
    await waitFor(() => expect(addFeederMember).toHaveBeenCalledWith(8, { user_id: 2 }));
    fireEvent.click(maple);
    await waitFor(() => expect(removeFeederMember).toHaveBeenCalledWith(7, 2));
  });

  it("changes a role through its own route", async () => {
    vi.mocked(updateUser).mockResolvedValue({});
    vi.mocked(setUserRole).mockResolvedValue({});
    const dialog = manage(sam);
    fireEvent.change(within(dialog).getByLabelText("Role"), { target: { value: "owner" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save details" }));
    await within(dialog).findByText("Saved.");
    expect(setUserRole).toHaveBeenCalledWith(2, "owner");
  });

  it("shows the last-owner refusal", async () => {
    vi.mocked(updateUser).mockResolvedValue({});
    vi.mocked(setUserRole).mockRejectedValue(
      Object.assign(new Error("The last owner cannot be demoted."), { status: 409 }));
    const dialog = manage(me);
    fireEvent.change(within(dialog).getByLabelText("Role"), { target: { value: "viewer" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save details" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The last owner cannot be demoted.");
  });

  it("resets a password with the temporary password note", async () => {
    vi.mocked(changePassword).mockResolvedValue(null);
    const dialog = manage(sam);
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset password…" }));
    expect(within(dialog).getByText(/share it with them/)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Temporary password/), { target: { value: "newpass12" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset password" }));
    await within(dialog).findByText(/Password reset/);
    expect(changePassword).toHaveBeenCalledWith(2, { new_password: "newpass12" });
  });

  it("signs a user out everywhere", async () => {
    vi.mocked(signOutUser).mockResolvedValue(null);
    const dialog = manage(sam);
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign out everywhere" }));
    await within(dialog).findByText(/signed out on every device/);
    expect(signOutUser).toHaveBeenCalledWith(2);
  });

  it("removes a user only after a confirm, and shows a refusal", async () => {
    vi.mocked(deleteUser).mockRejectedValue(
      Object.assign(new Error("Sam Norris owns Porch. A user who owns a feeder cannot be removed."),
        { status: 409 }));
    const dialog = manage(sam);
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove user…" }));
    expect(deleteUser).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove Sam Norris" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Sam Norris owns Porch.");
    expect(deleteUser).toHaveBeenCalledWith(2);
  });

  it("gives an owner no way to reset, sign out or remove themselves", async () => {
    const dialog = manage(me);
    await within(dialog).findByRole("checkbox", { name: /^Maple/ });
    expect(within(dialog).queryByRole("button", { name: "Remove user…" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Reset password…" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Sign out everywhere" })).toBeNull();
    // Owning a feeder is not a membership to untick.
    expect(within(dialog).getByRole("checkbox", { name: /^Maple/ })).toBeDisabled();
  });
});
