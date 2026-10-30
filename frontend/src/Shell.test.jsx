// The "Latest bird" navigation: four tabs, More for the rest, and the screen
// ids an installed app may still deep-link with.
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";

vi.mock("./DataContext.jsx", () => ({
  useData: () => ({
    data: { ME: { name: "Dominic Norris", role: "owner" } },
    live: true,
    reload: () => {},
    loading: false,
  }),
}));

import { TABS, TabBar, TopBar, MoreMenu } from "./Shell.jsx";
import { initialRoute } from "./App.jsx";

describe("navigation", () => {
  it("has the four tabs in design order", () => {
    expect(TABS.map(t => t.label)).toEqual(["Latest", "Species", "History", "Feeders"]);
  });

  it("puts the four tabs and More in the phone tab bar", () => {
    const setRoute = vi.fn();
    const onMore = vi.fn();
    render(<TabBar route="species" setRoute={setRoute} moreOpen={false} onMore={onMore} />);
    const bar = screen.getByRole("navigation");
    const labels = within(bar).getAllByRole("button").map(b => b.textContent);
    expect(labels).toEqual(["Latest", "Species", "History", "Feeders", "More"]);
    expect(within(bar).getByRole("button", { name: "Species" })).toHaveAttribute("aria-current", "page");

    fireEvent.click(within(bar).getByRole("button", { name: "History" }));
    expect(setRoute).toHaveBeenCalledWith("history");
    fireEvent.click(within(bar).getByRole("button", { name: "More" }));
    expect(onMore).toHaveBeenCalled();
  });

  it("puts the four tabs in the desktop top bar, with the live status", () => {
    render(<TopBar route="latest" setRoute={() => {}} moreOpen={false} onMore={() => {}} />);
    const tabs = screen.getByRole("navigation", { name: "Primary" });
    expect(within(tabs).getAllByRole("button").map(b => b.textContent))
      .toEqual(["Latest", "Species", "History", "Feeders"]);
    expect(screen.getByRole("status")).toHaveTextContent("Live");
  });

  it("keeps Users, Settings and sign out under More", () => {
    const setRoute = vi.fn();
    const onLogout = vi.fn();
    const onClose = vi.fn();
    render(<MoreMenu route="latest" setRoute={setRoute} onLogout={onLogout} onClose={onClose} />);
    const menu = screen.getByRole("menu", { name: "More" });
    expect(within(menu).getAllByRole("menuitem").map(b => b.textContent))
      .toEqual(["Users", "Settings", "Sign out"]);

    fireEvent.click(within(menu).getByRole("menuitem", { name: "Settings" }));
    expect(setRoute).toHaveBeenCalledWith("settings");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Sign out" }));
    expect(onLogout).toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
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
