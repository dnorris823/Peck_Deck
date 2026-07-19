import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getToken, setToken, clearToken,
  login, apiGet, apiSend, AuthError,
} from "./api.js";

// Helper: build a fetch Response-like object with the bits api.js reads.
function mockResponse({ status = 200, ok, json, text } = {}) {
  return {
    status,
    ok: ok ?? (status >= 200 && status < 300),
    json: async () => {
      if (json === undefined) throw new Error("no json body");
      return json;
    },
    text: async () => text ?? "",
  };
}

beforeEach(() => {
  localStorage.clear();
  global.fetch = vi.fn();
});

describe("token storage", () => {
  it("round-trips through localStorage", () => {
    expect(getToken()).toBeNull();
    setToken("abc.def.ghi");
    expect(getToken()).toBe("abc.def.ghi");
    clearToken();
    expect(getToken()).toBeNull();
  });
});

describe("login", () => {
  it("stores the access token on success", async () => {
    fetch.mockResolvedValue(mockResponse({ json: { access_token: "tok-123" } }));
    const data = await login("dom@peck.deck", "hunter2");
    expect(data.access_token).toBe("tok-123");
    expect(getToken()).toBe("tok-123");
    expect(fetch).toHaveBeenCalledWith("/api/login", expect.objectContaining({ method: "POST" }));
  });

  it("throws AuthError on 401", async () => {
    fetch.mockResolvedValue(mockResponse({ status: 401 }));
    await expect(login("dom@peck.deck", "wrong")).rejects.toBeInstanceOf(AuthError);
    expect(getToken()).toBeNull();
  });

  it("throws a generic error on other non-ok statuses", async () => {
    fetch.mockResolvedValue(mockResponse({ status: 500 }));
    await expect(login("dom@peck.deck", "x")).rejects.toThrow(/500/);
  });

  it("throws a reachability error when fetch rejects", async () => {
    fetch.mockRejectedValue(new TypeError("network down"));
    await expect(login("dom@peck.deck", "x")).rejects.toThrow(/reach the server/);
  });
});

describe("apiGet", () => {
  it("attaches the bearer token and returns parsed JSON", async () => {
    setToken("tok-xyz");
    fetch.mockResolvedValue(mockResponse({ json: [{ id: 1 }] }));
    const out = await apiGet("/species");
    expect(out).toEqual([{ id: 1 }]);
    expect(fetch).toHaveBeenCalledWith("/api/species", {
      headers: { Authorization: "Bearer tok-xyz" },
    });
  });

  it("clears the token and throws AuthError on 401", async () => {
    setToken("stale");
    fetch.mockResolvedValue(mockResponse({ status: 401 }));
    await expect(apiGet("/users")).rejects.toBeInstanceOf(AuthError);
    expect(getToken()).toBeNull();
  });

  it("throws with the status code on other failures", async () => {
    fetch.mockResolvedValue(mockResponse({ status: 404 }));
    await expect(apiGet("/missing")).rejects.toThrow(/404/);
  });
});

describe("apiSend", () => {
  it("sends a JSON body and returns the parsed response", async () => {
    setToken("tok");
    fetch.mockResolvedValue(mockResponse({ json: { id: 5, name: "Backyard" } }));
    const out = await apiSend("/devices", "POST", { name: "Backyard" });
    expect(out).toEqual({ id: 5, name: "Backyard" });
    const [, opts] = fetch.mock.calls[0];
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ name: "Backyard" });
    expect(opts.headers["Content-Type"]).toBe("application/json");
  });

  it("returns null for a 204 No Content", async () => {
    fetch.mockResolvedValue(mockResponse({ status: 204 }));
    const out = await apiSend("/users/1", "PUT", { name: "X" });
    expect(out).toBeNull();
  });

  it("surfaces the backend's detail message and status on error", async () => {
    fetch.mockResolvedValue(mockResponse({ status: 409, json: { detail: "That email is already registered." } }));
    await expect(apiSend("/users", "POST", {})).rejects.toMatchObject({
      message: "That email is already registered.",
      status: 409,
    });
  });

  it("falls back to a generic message when the error body isn't JSON", async () => {
    fetch.mockResolvedValue(mockResponse({ status: 400 })); // json() throws
    await expect(apiSend("/users", "POST", {})).rejects.toThrow(/400/);
  });

  it("clears the token and throws AuthError on 401", async () => {
    setToken("stale");
    fetch.mockResolvedValue(mockResponse({ status: 401 }));
    await expect(apiSend("/users/1", "PUT", {})).rejects.toBeInstanceOf(AuthError);
    expect(getToken()).toBeNull();
  });
});
