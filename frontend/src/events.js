// Live sighting stream — the client half of GET /events.
//
// Not `EventSource`. It cannot send an Authorization header, and every route on
// this API is Bearer-JWT; the alternatives were a token in the query string
// (which lands in access logs) or moving the whole app to cookie auth to suit
// one endpoint. So the stream is read with `fetch` and the SSE framing is parsed
// here — about forty lines, and the auth model is untouched.
//
// What `EventSource` would have given us for free, and therefore has to live
// here: reconnection with backoff, and resuming from the last event id so a
// dropped connection replays what it missed instead of leaving a hole.
import { getToken, clearToken, AuthError } from "./api.js";

const BASE_RETRY_MS = 3000;
const MAX_RETRY_MS = 60000;

// Split on a blank line — SSE's record separator. Servers may use \n or \r\n,
// and Litestar uses \r\n, so both have to be accepted.
const RECORD_SEP = /\r?\n\r?\n/;

/**
 * Parse one SSE record into `{ event, data, id, retry }`.
 * Comment lines (":keepalive") carry no fields and yield an empty record.
 */
export function parseRecord(raw) {
  const out = { event: null, data: "", id: null, retry: null };
  const dataLines = [];

  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // "field: value" — exactly one leading space is part of the framing.
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") out.event = value;
    else if (field === "data") dataLines.push(value);
    else if (field === "id") out.id = value;
    else if (field === "retry") out.retry = Number(value) || null;
  }

  out.data = dataLines.join("\n");
  return out;
}

/**
 * Hold GET /events open and invoke the handlers as messages arrive.
 *
 * Returns a `stop()` function. Callers must call it — an abandoned stream keeps
 * a connection open and a reconnect timer armed for the life of the tab.
 *
 * @param {object} handlers
 * @param {(sighting: object) => void} handlers.onSighting  a new visit arrived
 * @param {() => void} handlers.onResync   the stream lost track; refetch everything
 * @param {(live: boolean) => void} [handlers.onStatus]  connected / disconnected
 * @param {() => void} [handlers.onAuthError]  the token was rejected
 */
export function openSightingStream({ onSighting, onResync, onStatus, onAuthError }) {
  let stopped = false;
  let controller = null;
  let timer = null;
  let attempt = 0;
  let lastEventId = null;
  // Server-suggested backoff (SSE `retry:`), preferred over ours when present.
  let retryHint = null;

  async function connect() {
    if (stopped) return;
    controller = new AbortController();

    try {
      const token = getToken();
      const res = await fetch("/api/events", {
        headers: {
          Accept: "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          // Our own resume signal. The browser sets this automatically for
          // EventSource; reading the stream by hand means setting it by hand.
          ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
        },
        signal: controller.signal,
      });

      if (res.status === 401) {
        // Terminal, and `stopped` is what makes it terminal: a bare `return`
        // still runs the finally block below, which would reschedule and
        // reconnect-loop against a token the server has already rejected.
        stopped = true;
        clearToken();
        onAuthError?.(new AuthError("Your session has expired. Please sign in again."));
        return;
      }
      if (!res.ok || !res.body) throw new Error(`stream failed (${res.status})`);

      attempt = 0;
      onStatus?.(true);
      await pump(res.body);
    } catch (err) {
      if (stopped || err?.name === "AbortError") return;
      // Everything else — server restart, network drop, proxy timeout — is a
      // reconnect, not an error the user needs to see. The offline banner is
      // already the app's answer to "the network is gone".
    } finally {
      if (!stopped) {
        onStatus?.(false);
        scheduleReconnect();
      }
    }
  }

  async function pump(body) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (!stopped) {
      const { value, done } = await reader.read();
      if (done) break; // Server closed; the finally block reconnects.
      buffer += decoder.decode(value, { stream: true });

      // Everything up to the final separator is complete; the remainder is a
      // partial record awaiting more bytes.
      const records = buffer.split(RECORD_SEP);
      buffer = records.pop() ?? "";
      for (const raw of records) dispatch(parseRecord(raw));
    }
  }

  function dispatch({ event, data, id, retry }) {
    if (retry) retryHint = retry;
    // Only advance the resume point for records that carry an id, so a
    // heartbeat can't move it past an event we haven't handled.
    if (id) lastEventId = id;

    if (event === "sighting") {
      try {
        onSighting(JSON.parse(data));
      } catch {
        // A payload this build can't read is a resync, not a crash.
        onResync();
      }
    } else if (event === "resync") {
      onResync();
    }
    // "ready" needs no handling — onStatus(true) already fired on connect.
  }

  function scheduleReconnect() {
    // Exponential backoff with jitter. Without the jitter, every tab that was
    // watching a backend when it restarted comes back at the same instant.
    const base = retryHint || BASE_RETRY_MS;
    const delay = Math.min(base * 2 ** attempt, MAX_RETRY_MS);
    attempt += 1;
    timer = setTimeout(connect, delay * (0.5 + Math.random() * 0.5));
  }

  connect();

  return function stop() {
    stopped = true;
    clearTimeout(timer);
    controller?.abort();
  };
}
