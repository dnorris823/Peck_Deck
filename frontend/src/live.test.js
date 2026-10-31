// live.js against a fake RTCPeerConnection and a fake fetch: the offer, the
// answer, DELETE on hide, and the retry after a failure.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  ICE_GATHER_MS, MAX_RETRY_MS, UNREACHABLE_AFTER, openLiveStream, readStats, retryDelay,
} from "./live.js";

const OFFER = "v=0\r\no=offer";
const ANSWER = "v=0\r\no=answer";

// Gathering completes on its own unless a test says otherwise.
let gatherCompletes = true;
let peers = [];

class FakePeer {
  constructor() {
    this.iceGatheringState = "new";
    this.iceConnectionState = "new";
    this.localDescription = null;
    this.remoteDescription = null;
    this.closed = false;
    this.transceivers = [];
    this.listeners = {};
    peers.push(this);
  }
  addTransceiver(kind, init) { this.transceivers.push({ kind, ...init }); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter(f => f !== fn);
  }
  async createOffer() { return { type: "offer", sdp: OFFER }; }
  async setLocalDescription(desc) {
    this.localDescription = desc;
    this.iceGatheringState = "gathering";
    if (gatherCompletes) {
      queueMicrotask(() => {
        this.iceGatheringState = "complete";
        (this.listeners.icegatheringstatechange || []).forEach(f => f());
      });
    }
  }
  async setRemoteDescription(desc) { this.remoteDescription = desc; }
  async getStats() { return new Map(); }
  close() { this.closed = true; }
  ice(state) {
    this.iceConnectionState = state;
    this.oniceconnectionstatechange?.();
  }
}

function answerResponse(session = "abc") {
  return new Response(ANSWER, {
    status: 201,
    headers: { "Content-Type": "application/sdp", Location: `/devices/7/live/whep/${session}` },
  });
}

function setVisibility(state) {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

// Let pending promises and the microtasks they queue run. A real setImmediate
// runs only after the microtask queue drains, however many hops it takes.
// Counting ticks broke on Node 20, where Response.text() needs more of them
// than on Node 24.
async function settle() {
  await new Promise(resolve => setImmediate(resolve));
}

let fetchMock;
let stop;

beforeEach(() => {
  // setImmediate stays real so settle() can use it.
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  gatherCompletes = true;
  peers = [];
  vi.stubGlobal("RTCPeerConnection", FakePeer);
  fetchMock = vi.fn(async () => answerResponse());
  vi.stubGlobal("fetch", fetchMock);
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  localStorage.setItem("peckdeck_token", "jwt");
});

afterEach(() => {
  stop?.();
  stop = null;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function open() {
  const statuses = [];
  const video = { srcObject: null };
  stop = openLiveStream({ deviceId: 7, video, onStatus: s => statuses.push(s) });
  return { statuses, video, last: () => statuses[statuses.length - 1] };
}

const calls = (method) => fetchMock.mock.calls.filter(([, init]) => (init?.method || "GET") === method);

describe("openLiveStream", () => {
  it("posts a receive-only offer with the JWT and applies the answer", async () => {
    const { last } = open();
    expect(last().phase).toBe("connecting");
    await settle();

    const [url, init] = calls("POST")[0];
    expect(url).toBe("/api/devices/7/live/whep");
    expect(init.headers["Content-Type"]).toBe("application/sdp");
    expect(init.headers.Authorization).toBe("Bearer jwt");
    expect(init.body).toBe(OFFER);

    const pc = peers[0];
    expect(pc.transceivers).toEqual([{ kind: "video", direction: "recvonly" }]);
    expect(pc.remoteDescription).toEqual({ type: "answer", sdp: ANSWER });

    pc.ice("connected");
    expect(last().phase).toBe("live");
  });

  it("sends the offer after 2 seconds when gathering never completes", async () => {
    gatherCompletes = false;
    open();
    await settle();
    expect(calls("POST")).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(ICE_GATHER_MS);
    expect(calls("POST")).toHaveLength(1);
  });

  it("sends DELETE on hide and starts again when visible", async () => {
    const { last } = open();
    await settle();
    peers[0].ice("connected");

    setVisibility("hidden");
    expect(last().phase).toBe("paused");
    expect(peers[0].closed).toBe(true);
    const [url, init] = calls("DELETE")[0];
    expect(url).toBe("/api/devices/7/live/whep/abc");
    expect(init.keepalive).toBe(true);
    expect(init.headers.Authorization).toBe("Bearer jwt");

    setVisibility("visible");
    expect(last().phase).toBe("connecting");
    await settle();
    expect(calls("POST")).toHaveLength(2);
    expect(peers).toHaveLength(2);
  });

  it("sends DELETE on pagehide and when stopped", async () => {
    open();
    await settle();
    window.dispatchEvent(new Event("pagehide"));
    expect(calls("DELETE")).toHaveLength(1);

    setVisibility("visible");
    await settle();
    stop();
    expect(calls("DELETE")).toHaveLength(2);
  });

  it("ends a session whose answer lands after the hide", async () => {
    let release;
    fetchMock.mockImplementationOnce(() => new Promise(r => { release = r; }));
    open();
    await settle();
    setVisibility("hidden");
    expect(calls("DELETE")).toHaveLength(0);

    release(answerResponse("late"));
    await settle();
    expect(calls("DELETE")[0][0]).toBe("/api/devices/7/live/whep/late");
  });

  it("shows Reconnecting on ICE failure and retries with backoff", async () => {
    const { last } = open();
    await settle();
    peers[0].ice("connected");
    peers[0].ice("failed");

    expect(last().phase).toBe("reconnecting");
    expect(calls("DELETE")).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(retryDelay(0) - 1);
    expect(calls("POST")).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls("POST")).toHaveLength(2);

    peers[1].ice("connected");
    expect(last().phase).toBe("live");
  });

  it("retries a failed POST and says when the feeder looks unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError("network"));
    const { last } = open();
    await settle();
    expect(last().phase).toBe("reconnecting");
    expect(last().unreachable).toBe(false);

    for (let i = 0; i < UNREACHABLE_AFTER - 1; i++) {
      await vi.advanceTimersByTimeAsync(retryDelay(i));
    }
    expect(calls("POST")).toHaveLength(UNREACHABLE_AFTER);
    expect(last().unreachable).toBe(true);
  });

  it("reports a 503 as offline and asks again every 30 seconds", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "feeder not streaming" }), {
      status: 503, headers: { "Content-Type": "application/json" },
    }));
    const { statuses, last } = open();
    await settle();
    expect(last().phase).toBe("offline");

    await vi.advanceTimersByTimeAsync(MAX_RETRY_MS);
    expect(calls("POST")).toHaveLength(2);
    // Still offline throughout, with no "Reconnecting" between the asks.
    expect(statuses.slice(1).every(s => s.phase === "offline")).toBe(true);
  });

  it("stops on a 404 instead of retrying", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 404 }));
    const { last } = open();
    await settle();
    expect(last().phase).toBe("error");
    await vi.advanceTimersByTimeAsync(MAX_RETRY_MS * 2);
    expect(calls("POST")).toHaveLength(1);
  });

  it("waits for the page to be visible before it starts", async () => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    const { last } = open();
    await settle();
    expect(last().phase).toBe("paused");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("retryDelay", () => {
  it("doubles from 1 second and stops at 30", () => {
    expect([0, 1, 2, 3, 4, 5, 6].map(retryDelay))
      .toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);
  });
});

describe("readStats", () => {
  it("reads frame rate and delay from the inbound video", () => {
    const report = new Map([
      ["in", { type: "inbound-rtp", kind: "video", framesPerSecond: 29.7, jitterBufferDelay: 3, jitterBufferEmittedCount: 30, timestamp: 1000, framesDecoded: 300 }],
      ["pair", { type: "candidate-pair", nominated: true, currentRoundTripTime: 0.04 }],
    ]);
    expect(readStats(report)).toMatchObject({ fps: 30, delayMs: 120 });
  });

  it("works out the frame rate from frames decoded when the browser gives none", () => {
    const report = new Map([
      ["in", { type: "inbound-rtp", kind: "video", timestamp: 2000, framesDecoded: 330 }],
    ]);
    expect(readStats(report, { timestamp: 1000, framesDecoded: 300 }).fps).toBe(30);
  });

  it("returns nulls before any video arrives", () => {
    expect(readStats(new Map())).toEqual({ fps: null, delayMs: null, sample: null });
  });
});
