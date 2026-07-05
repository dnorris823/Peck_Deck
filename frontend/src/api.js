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
