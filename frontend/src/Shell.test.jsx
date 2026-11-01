// The "Latest bird" navigation: five tabs, More for the rest, and the screen
// ids an installed app may still deep-link with.
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, within, act } from "@testing-library/react";

// `stream.live` stands in for the GET /events status, so a test can drop it.
// `stream.devices` and `stream.feeder` drive the feeder picker.
const stream = vi.hoisted(() => ({ live: true, devices: [], feeder: null, setFeeder: null }));

vi.mock("./DataContext.jsx", () => ({
  useData: () => ({
    data: { ME: { name: "Dominic Norris", role: "owner" }, DEVICES: stream.devices },
    live: stream.live,
    reload: () => {},
    loading: false,
    feeder: stream.feeder,
    setFeeder: stream.setFeeder,
  }),
}));

import {
  TABS, TabBar, TopBar, MoreMenu, FeederPicker, LIVE_GRACE_MS, moreFor, allowedRoute,
} from "./Shell.jsx";
import { initialRoute } from "./App.jsx";

describe("navigation", () => {
  it("has the five tabs in design order", () => {
    expect(TABS.map(t => t.label)).toEqual(["Latest", "Live", "Species", "History", "Feeders"]);
  });

  it("puts the five tabs and More in the phone tab bar", () => {
    const setRoute = vi.fn();
    const onMore = vi.fn();
    render(<TabBar route="species" setRoute={setRoute} moreOpen={false} onMore={onMore} />);
    const bar = screen.getByRole("navigation");
    const labels = within(bar).getAllByRole("button").map(b => b.textContent);
    expect(labels).toEqual(["Latest", "Live", "Species", "History", "Feeders", "More"]);
    expect(within(bar).getByRole("button", { name: "Species" })).toHaveAttribute("aria-current", "page");

    fireEvent.click(within(bar).getByRole("button", { name: "History" }));
    expect(setRoute).toHaveBeenCalledWith("history");
    fireEvent.click(within(bar).getByRole("button", { name: "More" }));
    expect(onMore).toHaveBeenCalled();
  });

  it("puts the five tabs in the desktop top bar", () => {
    render(<TopBar route="latest" setRoute={() => {}} moreOpen={false} onMore={() => {}} />);
    const tabs = screen.getByRole("navigation", { name: "Primary" });
    expect(within(tabs).getAllByRole("button").map(b => b.textContent))
      .toEqual(["Latest", "Live", "Species", "History", "Feeders"]);
    expect(screen.getByRole("button", { name: "Refresh data" })).toBeInTheDocument();
  });

  it("keeps Animals, Users, Settings and sign out under More", () => {
    const setRoute = vi.fn();
    const onLogout = vi.fn();
    const onClose = vi.fn();
    render(<MoreMenu route="latest" setRoute={setRoute} onLogout={onLogout} onClose={onClose} />);
    const menu = screen.getByRole("menu", { name: "More" });
    expect(within(menu).getAllByRole("menuitem").map(b => b.textContent))
      .toEqual(["Animals", "Users", "Settings", "Sign out"]);

    fireEvent.click(within(menu).getByRole("menuitem", { name: "Settings" }));
    expect(setRoute).toHaveBeenCalledWith("settings");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Sign out" }));
    expect(onLogout).toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});

describe("live status", () => {
  afterEach(() => {
    stream.live = true;
    vi.useRealTimers();
  });

  const topBar = () => <TopBar route="latest" setRoute={() => {}} moreOpen={false} onMore={() => {}} />;

  it("shows nothing while the stream is connected", () => {
    render(topBar());
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(within(screen.getByRole("status")).queryByText("Live")).not.toBeInTheDocument();
  });

  it("shows the disconnected state once the stream has been down past the grace period", () => {
    vi.useFakeTimers();
    stream.live = false;
    render(topBar());
    const status = screen.getByRole("status");
    expect(status).toBeEmptyDOMElement();

    act(() => { vi.advanceTimersByTime(LIVE_GRACE_MS); });
    expect(status).toHaveTextContent("Reconnecting…");
    expect(status.querySelector(".live-pill"))
      .toHaveAttribute("title", "Not receiving live updates. Refresh to catch up.");
    expect(screen.getByRole("button", { name: "Refresh data" })).toBeInTheDocument();
  });

  it("does not flash through a reconnect shorter than the grace period", () => {
    vi.useFakeTimers();
    const { rerender } = render(topBar());
    const status = screen.getByRole("status");

    stream.live = false;
    rerender(topBar());
    act(() => { vi.advanceTimersByTime(LIVE_GRACE_MS - 1); });
    stream.live = true;
    rerender(topBar());
    act(() => { vi.advanceTimersByTime(LIVE_GRACE_MS); });
    expect(status).toBeEmptyDOMElement();
  });

  it("clears the disconnected state when the stream comes back", () => {
    vi.useFakeTimers();
    stream.live = false;
    const { rerender } = render(topBar());
    act(() => { vi.advanceTimersByTime(LIVE_GRACE_MS); });
    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting…");

    stream.live = true;
    rerender(topBar());
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});

describe("initialRoute", () => {
  it("opens a screen named in ?screen=", () => {
    expect(initialRoute("?screen=species")).toBe("species");
    expect(initialRoute("?screen=history")).toBe("history");
  });

  it("maps the ids from before the redesign, which installed shortcuts still use", () => {
    expect(initialRoute("?screen=dashboard")).toBe("latest");
    expect(initialRoute("?screen=sightings")).toBe("history");
    expect(initialRoute("?screen=devices")).toBe("feeders");
  });

  it("falls back to Latest", () => {
    expect(initialRoute("")).toBe("latest");
    expect(initialRoute("?screen=nope")).toBe("latest");
  });
});

describe("owner-only screens", () => {
  it("leaves Users out of a viewer's More menu", () => {
    expect(moreFor({ role: "viewer" }).map(n => n.id)).toEqual(["animals", "settings"]);
    expect(moreFor({ role: "owner" }).map(n => n.id)).toEqual(["animals", "users", "settings"]);
  });

  it("offers Compare only to a user who sees two or more feeders", () => {
    const one = [{ id: 1 }];
    const two = [{ id: 1 }, { id: 2 }];
    expect(moreFor({ role: "viewer" }, one).map(n => n.id)).not.toContain("compare");
    expect(moreFor({ role: "viewer" }, two).map(n => n.id)).toEqual(["animals", "compare", "settings"]);
  });

  it("sends a viewer who asks for Users to Latest", () => {
    expect(allowedRoute("users", { role: "viewer" })).toBe("latest");
    expect(allowedRoute("users", { role: "owner" })).toBe("users");
    expect(allowedRoute("settings", { role: "viewer" })).toBe("settings");
  });
});

describe("feeder picker", () => {
  const MAPLE = { id: 1, name: "Backyard Maple" };
  const PORCH = { id: 2, name: "Dad's Porch" };

  afterEach(() => {
    stream.devices = [];
    stream.feeder = null;
    stream.setFeeder = null;
  });

  it("hides for a user who sees one feeder", () => {
    stream.devices = [MAPLE];
    render(<FeederPicker route="latest" />);
    expect(screen.queryByRole("combobox", { name: "Feeder" })).not.toBeInTheDocument();
  });

  it("offers all feeders or one, and sets the scope", () => {
    stream.devices = [MAPLE, PORCH];
    stream.feeder = 2;
    stream.setFeeder = vi.fn();
    render(<TopBar route="species" setRoute={() => {}} moreOpen={false} onMore={() => {}} />);
    const picker = screen.getByRole("combobox", { name: "Feeder" });
    expect(picker).toHaveValue("2");
    expect(within(picker).getAllByRole("option").map(o => o.textContent))
      .toEqual(["All feeders", "Backyard Maple", "Dad's Porch"]);

    fireEvent.change(picker, { target: { value: "1" } });
    expect(stream.setFeeder).toHaveBeenLastCalledWith(1);
    fireEvent.change(picker, { target: { value: "all" } });
    expect(stream.setFeeder).toHaveBeenLastCalledWith(null);
  });

  it("shows on Home, Species and Animals only", () => {
    stream.devices = [MAPLE, PORCH];
    for (const route of ["latest", "species", "animals"]) {
      const { unmount } = render(<FeederPicker route={route} />);
      expect(screen.getByRole("combobox", { name: "Feeder" })).toBeInTheDocument();
      unmount();
    }
    for (const route of ["history", "live", "feeders", "settings"]) {
      const { unmount } = render(<FeederPicker route={route} />);
      expect(screen.queryByRole("combobox", { name: "Feeder" })).not.toBeInTheDocument();
      unmount();
    }
  });
});
