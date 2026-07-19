import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("./api.js", () => ({ login: vi.fn() }));

import { login } from "./api.js";
import { Login } from "./Login.jsx";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Login", () => {
  it("submits trimmed credentials and calls onSuccess", async () => {
    const user = userEvent.setup();
    login.mockResolvedValue({ access_token: "tok" });
    const onSuccess = vi.fn();
    render(<Login onSuccess={onSuccess} />);

    await user.type(screen.getByLabelText("Email"), "  dom@peck.deck  ");
    await user.type(screen.getByLabelText("Password"), "hunter2");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(login).toHaveBeenCalledWith("dom@peck.deck", "hunter2");
  });

  it("shows the error message and does not call onSuccess on failure", async () => {
    const user = userEvent.setup();
    login.mockRejectedValue(new Error("Invalid email or password."));
    const onSuccess = vi.fn();
    render(<Login onSuccess={onSuccess} />);

    await user.type(screen.getByLabelText("Email"), "dom@peck.deck");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
