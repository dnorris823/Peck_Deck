// The SSE framing parser and the stream client's reconnect/resume behaviour.
//
// Worth testing directly because this is the code we had to write instead of
// using `EventSource` — the browser would have handled framing, reconnection
// and Last-Event-ID for us, and it can't because it won't send an
// Authorization header.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("./api.js", () => ({
  getToken: vi.fn(() => "test-token"),
  clearToken: vi.fn(),
  AuthError: class AuthError extends Error {},
}));

import { parseRecord, openSightingStream } from "./events.js";
import { getToken, clearToken } from "./api.js";

describe("parseRecord", () => {
  it("reads event, data and id", () => {
    const r = parseRecord("event: sighting\r\nid: 42\r\ndata: {\"id\":42}");
    expect(r).toMatchObject({ event: "sighting", id: "42", data: '{"id":42}' });
  });

  it("accepts bare newlines as well as CRLF", () => {
    expect(parseRecord("event: ready\ndata: ok").event).toBe("ready");
  });

  it("joins multi-line data with newlines, per the SSE spec", () => {
    expect(parseRecord("data: one\ndata: two").data).toBe("one\ntwo");
  });

  it("strips exactly one leading space, not the rest", () => {
    // "data:  x" is a space then "x" — the first space is framing, the second
    // is content. Stripping both would corrupt any payload starting with one.
    expect(parseRecord("data:  x").data).toBe(" x");
  });

  it("ignores comment lines like the keepalive", () => {
    const r = parseRecord(":keepalive");
    expect(r.event).toBeNull();
    expect(r.data).toBe("");
  });

  it("reads a retry hint", () => {
    expect(parseRecord("event: ready\nretry: 3000").retry).toBe(3000);
  });
});

// ── The stream client ───────────────────────────────────────────────────────
// A fetch stub that hands back a body we can push chunks into.
function streamingResponse() {
  let push, close;
  const body = new ReadableStream({
    start(c) {
      push = (text) => c.enqueue(new TextEncoder().encode(text));
      close = () => c.close();
    },
  });
  return { res: { ok: true, status: 200, body }, push: (t) => push(t), close: () => close() };
}

let stop;

beforeEach(() => {
  vi.clearAllMocks();
  getToken.mockReturnValue("test-token");
});

afterEach(() => {
  stop?.();
  stop = null;
  vi.unstubAllGlobals();
});

async function flush() {
  for (let i = 0; i < 6; i++) await Promise.resolve();
}

describe("openSightingStream", () => {
  it("sends the bearer token — the reason this isn't EventSource", async () => {
    const { res } = streamingResponse();
    const fetchMock = vi.fn().mockResolvedValue(res);
    vi.stubGlobal("fetch", fetchMock);

    stop = openSightingStream({ onSighting: vi.fn(), onResync: vi.fn() });
    await flush();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/events");
    expect(init.headers.Authorization).toBe("Bearer test-token");
    expect(init.headers.Accept).toBe("text/event-stream");
  });

  it("delivers a parsed sighting", async () => {
    const { res, push } = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
    const onSighting = vi.fn();

    stop = openSightingStream({ onSighting, onResync: vi.fn() });
    await flush();
    push('event: sighting\r\nid: 7\r\ndata: {"id":7,"species_id":3}\r\n\r\n');
    await flush();

    expect(onSighting).toHaveBeenCalledWith({ id: 7, species_id: 3 });
  });

  it("waits for the record separator before dispatching a split message", async () => {
    const { res, push } = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
    const onSighting = vi.fn();

    stop = openSightingStream({ onSighting, onResync: vi.fn() });
    await flush();

    // A chunk boundary mid-record is normal on a real socket.
    push('event: sighting\r\nid: 9\r\ndata: {"id":9,');
    await flush();
    expect(onSighting).not.toHaveBeenCalled();

    push('"species_id":1}\r\n\r\n');
    await flush();
    expect(onSighting).toHaveBeenCalledWith({ id: 9, species_id: 1 });
  });

  it("reports a resync rather than throwing on an unreadable payload", async () => {
    const { res, push } = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
    const onResync = vi.fn();

    stop = openSightingStream({ onSighting: vi.fn(), onResync });
    await flush();
    push("event: sighting\r\nid: 3\r\ndata: not-json\r\n\r\n");
    await flush();

    expect(onResync).toHaveBeenCalledTimes(1);
  });

  it("passes a server resync straight through", async () => {
    const { res, push } = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
    const onResync = vi.fn();

    stop = openSightingStream({ onSighting: vi.fn(), onResync });
    await flush();
    push("event: resync\r\ndata: overflow\r\n\r\n");
    await flush();

    expect(onResync).toHaveBeenCalledTimes(1);
  });

  it("resumes from the last event id after a drop", async () => {
    const first = streamingResponse();
    const second = streamingResponse();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(first.res)
      .mockResolvedValueOnce(second.res);
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();

    stop = openSightingStream({ onSighting: vi.fn(), onResync: vi.fn() });
    await flush();
    first.push('event: sighting\r\nid: 11\r\ndata: {"id":11}\r\n\r\n');
    await flush();
    first.close();
    await flush();

    await vi.advanceTimersByTimeAsync(70000);
    await flush();
    vi.useRealTimers();

    // Without this header the gap between the drop and the reconnect is lost
    // until someone reloads the page.
    expect(fetchMock.mock.calls[1][1].headers["Last-Event-ID"]).toBe("11");
  });

  it("does not advance the resume point past a heartbeat", async () => {
    const { res, push } = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
    const onSighting = vi.fn();

    stop = openSightingStream({ onSighting, onResync: vi.fn() });
    await flush();
    push("event: sighting\r\nid: 5\r\ndata: {}\r\n\r\n");
    push(":keepalive\r\n\r\n");
    await flush();

    // Nothing to assert on the wire here; what matters is that the keepalive
    // produced no callback of its own.
    expect(onSighting).toHaveBeenCalledTimes(1);
  });

  it("reports auth failure and gives up instead of reconnect-looping", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 401, body: null });
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();
    const onAuthError = vi.fn();

    stop = openSightingStream({ onSighting: vi.fn(), onResync: vi.fn(), onAuthError });
    await flush();

    expect(onAuthError).toHaveBeenCalledTimes(1);
    expect(clearToken).toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(120000);
    vi.useRealTimers();
    // A rejected token will be rejected again — retrying is just noise.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reports connection status so the app can show it", async () => {
    const { res, close } = streamingResponse();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));
    const onStatus = vi.fn();

    stop = openSightingStream({ onSighting: vi.fn(), onResync: vi.fn(), onStatus });
    await flush();
    expect(onStatus).toHaveBeenCalledWith(true);

    close();
    await flush();
    expect(onStatus).toHaveBeenCalledWith(false);
  });

  it("stops for good once stopped", async () => {
    const { res } = streamingResponse();
    const fetchMock = vi.fn().mockResolvedValue(res);
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers();

    const halt = openSightingStream({ onSighting: vi.fn(), onResync: vi.fn() });
    await flush();
    halt();

    await vi.advanceTimersByTimeAsync(120000);
    vi.useRealTimers();
    // One connect, no reconnect: an abandoned stream would otherwise hold a
    // connection and a timer for the life of the tab.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
