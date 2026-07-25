import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("./api.js", () => ({ fetchMeta: vi.fn(), login: vi.fn() }));

import { fetchMeta } from "./api.js";
import { DemoProvider, DemoBanner, DemoLoginHint } from "./Demo.jsx";
import { Login } from "./Login.jsx";

beforeEach(() => {
  vi.clearAllMocks();
});

function renderInProvider(ui) {
  return render(<DemoProvider>{ui}</DemoProvider>);
}

describe("DemoBanner", () => {
  it("stays hidden on a normal instance", async () => {
    fetchMeta.mockResolvedValue({ demo_mode: false, environment: "development" });
    renderInProvider(<DemoBanner />);

    await waitFor(() => expect(fetchMeta).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says both that the data is simulated and that writes won't stick", async () => {
    fetchMeta.mockResolvedValue({ demo_mode: true });
    renderInProvider(<DemoBanner />);

    const banner = await screen.findByRole("status");
    expect(banner).toHaveTextContent(/simulated/i);
    expect(banner).toHaveTextContent(/read-only/i);
  });

  it("stays hidden when /meta can't be reached", async () => {
    // fetchMeta swallows failures and returns null — a backend that predates
    // /meta must not leave a stale or spurious banner on screen.
    fetchMeta.mockResolvedValue(null);
    renderInProvider(<DemoBanner />);

    await waitFor(() => expect(fetchMeta).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("DemoLoginHint", () => {
  it("is hidden unless the backend published credentials", async () => {
    fetchMeta.mockResolvedValue({ demo_mode: true }); // demo, but no demo_login
    renderInProvider(<DemoLoginHint onUse={vi.fn()} />);

    await waitFor(() => expect(fetchMeta).toHaveBeenCalled());
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("hands the published credentials back on click", async () => {
    const user = userEvent.setup();
    const onUse = vi.fn();
    fetchMeta.mockResolvedValue({
      demo_mode: true,
      demo_login: { email: "dom@peck.deck", password: "peckdeck" },
    });
    renderInProvider(<DemoLoginHint onUse={onUse} />);

    await user.click(await screen.findByRole("button", { name: /dom@peck\.deck/ }));

    expect(onUse).toHaveBeenCalledWith("dom@peck.deck", "peckdeck");
  });
});

describe("Login on a demo instance", () => {
  it("fills the fields and signs in with the published account", async () => {
    const user = userEvent.setup();
    const { login } = await import("./api.js");
    login.mockResolvedValue({ access_token: "tok" });
    fetchMeta.mockResolvedValue({
      demo_mode: true,
      demo_login: { email: "dom@peck.deck", password: "peckdeck" },
    });
    const onSuccess = vi.fn();

    renderInProvider(<Login onSuccess={onSuccess} />);
    await user.click(await screen.findByRole("button", { name: /dom@peck\.deck/ }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(login).toHaveBeenCalledWith("dom@peck.deck", "peckdeck");
    // Filled in, not hidden — the visitor can see what they signed in as.
    expect(screen.getByLabelText("Email")).toHaveValue("dom@peck.deck");
  });

  it("leaves the normal sign-in form untouched", async () => {
    fetchMeta.mockResolvedValue({ demo_mode: false });
    renderInProvider(<Login onSuccess={vi.fn()} />);

    await waitFor(() => expect(fetchMeta).toHaveBeenCalled());
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.queryByText(/read-only station/i)).not.toBeInTheDocument();
  });
});
