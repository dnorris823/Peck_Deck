// API client — talks to the Litestar backend through Vite's /api proxy.
// Holds the JWT in localStorage and attaches it as a Bearer header.

const TOKEN_KEY = "peckdeck_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Thrown when the server rejects our credentials — the app uses this to bounce
// the user back to the login screen rather than showing a generic error.
export class AuthError extends Error {
  constructor(message) {
    super(message);
    this.name = "AuthError";
    this.isAuthError = true;
  }
}

// Instance metadata — public and unauthenticated, so it can be read before the
// login screen. Returns null on any failure: the demo banner is an enhancement,
// and a backend without /meta (or no backend at all) must still render the app
// rather than trapping the user behind an error.
export async function fetchMeta() {
  try {
    const res = await fetch("/api/meta");
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function login(email, password) {
  let res;
  try {
    res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new Error("Can't reach the server. Is the backend running?");
  }
  if (res.status === 401) throw new AuthError("Invalid email or password.");
  if (!res.ok) throw new Error(`Login failed (${res.status}).`);
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

export async function apiGet(path) {
  const token = getToken();
  let res;
  try {
    res = await fetch(`/api${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    throw new Error("Can't reach the server. Is the backend running?");
  }
  if (res.status === 401) {
    clearToken();
    throw new AuthError("Your session has expired. Please sign in again.");
  }
  if (!res.ok) throw new Error(`Request to ${path} failed (${res.status}).`);
  return res.json();
}

// Fetch binary bytes with the Bearer token attached. Every endpoint that serves
// bytes (the CSV/JSON export, sighting images) is auth-scoped, and neither an
// <a href> nor an <img src> can carry an Authorization header — so the bytes come
// through fetch and the caller turns them into a download or an object URL.
export async function apiFetchBinary(path, { failure = "Request" } = {}) {
  const token = getToken();
  let res;
  try {
    res = await fetch(`/api${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    throw new Error("Can't reach the server. Is the backend running?");
  }
  if (res.status === 401) {
    clearToken();
    throw new AuthError("Your session has expired. Please sign in again.");
  }
  if (!res.ok) throw new Error(`${failure} failed (${res.status}).`);
  return res;
}

// Fetch a file download as a Blob, with the filename the server suggested.
export async function apiDownload(path) {
  const res = await apiFetchBinary(path, { failure: "Export" });
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^"';]+)"?/.exec(disposition);
  return { blob: await res.blob(), filename: match ? match[1] : "export" };
}

// Fetch an image and return an object URL for it. The caller owns the URL and
// must revoke it — an un-revoked blob URL keeps the whole image alive for the
// lifetime of the document, which a scrolling gallery would notice.
export async function apiObjectUrl(path) {
  const res = await apiFetchBinary(path, { failure: "Image" });
  return URL.createObjectURL(await res.blob());
}

// DELETE with no body. Kept separate from apiSend because a DELETE that carries
// a Content-Type but no payload confuses some proxies, and the routes that need
// it (push subscriptions) identify the target with a query parameter.
export async function apiDelete(path) {
  const token = getToken();
  let res;
  try {
    res = await fetch(`/api${path}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    throw new Error("Can't reach the server. Is the backend running?");
  }
  if (res.status === 401) {
    clearToken();
    throw new AuthError("Your session has expired. Please sign in again.");
  }
  if (!res.ok) {
    const err = new Error(`Request to ${path} failed (${res.status}).`);
    err.status = res.status;
    throw err;
  }
  return null;
}

// Mutating request (PUT/POST) with a JSON body. Returns the parsed response,
// or null for a 204 No Content.
export async function apiSend(path, method, body) {
  const token = getToken();
  let res;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Can't reach the server. Is the backend running?");
  }
  if (res.status === 401) {
    clearToken();
    throw new AuthError("Your session has expired. Please sign in again.");
  }
  if (!res.ok) {
    // Surface the backend's `detail` (Litestar error body) plus the status code
    // so forms can show meaningful messages (409 duplicate, 400 bad password).
    let detail = null;
    try {
      detail = (await res.json())?.detail;
    } catch {
      /* non-JSON error body — fall back to a generic message */
    }
    const err = new Error(detail || `Request to ${path} failed (${res.status}).`);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}
