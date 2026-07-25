import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { isSupported, registerServiceWorker } from "./registerSW.js";

let register;

beforeEach(() => {
  register = vi.fn().mockResolvedValue({ update: vi.fn().mockResolvedValue(undefined) });
  navigator.serviceWorker = { register };
});

afterEach(() => {
  delete navigator.serviceWorker;
});

describe("registerServiceWorker", () => {
  it("reports support from the navigator", () => {
    expect(isSupported()).toBe(true);
    delete navigator.serviceWorker;
    expect(isSupported()).toBe(false);
  });

  it("does nothing in a dev build", async () => {
    // A worker in front of the Vite dev server serves stale modules and fights
    // HMR, so registration is production-only. (Tests run with PROD false.)
    expect(await registerServiceWorker()).toBeNull();
    expect(register).not.toHaveBeenCalled();
  });

  it("registers at the root scope when forced", async () => {
    const registration = await registerServiceWorker({ force: true });
    expect(registration).not.toBeNull();
    expect(register).toHaveBeenCalledWith("/sw.js", {
      scope: "/",
      // Without this an intermediary can pin the old worker indefinitely.
      updateViaCache: "none",
    });
  });

  it("checks for an update immediately rather than waiting for the browser", async () => {
    const registration = await registerServiceWorker({ force: true });
    expect(registration.update).toHaveBeenCalled();
  });

  it("returns null instead of throwing when registration fails", async () => {
    // An unavailable worker degrades the app to online-only — not an error screen.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    register.mockRejectedValue(new Error("insecure context"));
    expect(await registerServiceWorker({ force: true })).toBeNull();
    warn.mockRestore();
  });

  it("returns null when service workers are unsupported", async () => {
    delete navigator.serviceWorker;
    expect(await registerServiceWorker({ force: true })).toBeNull();
  });
});
