import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("./api.js", () => ({
  apiGet: vi.fn(),
  apiSend: vi.fn(),
  apiDelete: vi.fn(),
}));

import { apiDelete, apiGet, apiSend } from "./api.js";
import {
  currentSubscription, disablePush, enablePush, fetchPushConfig, permission,
  pushSupported, urlBase64ToUint8Array,
} from "./push.js";

// A P-256 public key is 65 bytes; base64url of 65 bytes is 87 unpadded chars.
const VAPID_KEY =
  "BEQo_llLpG5LjeGQRGznGT-Q93sO-_30UlE9s5FncvYO1oMCJbmz68bbUasl-PH9oX7cB43NSQu_de7QiiAyQpU";

function fakeSubscription(endpoint = "https://push.example.com/send/abc") {
  return {
    endpoint,
    toJSON: () => ({ endpoint, keys: { p256dh: "p", auth: "a" } }),
    unsubscribe: vi.fn().mockResolvedValue(true),
  };
}

/** Install a service-worker registration whose pushManager behaves as told. */
function installRegistration({ subscription = null, subscribeResult } = {}) {
  const registration = {
    pushManager: {
      getSubscription: vi.fn().mockResolvedValue(subscription),
      subscribe: vi.fn().mockResolvedValue(subscribeResult ?? fakeSubscription()),
    },
  };
  navigator.serviceWorker = { getRegistration: vi.fn().mockResolvedValue(registration) };
  return registration;
}

function installNotification(state = "default", requested = "granted") {
  const Notification = vi.fn();
  Notification.permission = state;
  Notification.requestPermission = vi.fn().mockResolvedValue(requested);
  window.Notification = Notification;
  globalThis.Notification = Notification;
  return Notification;
}

beforeEach(() => {
  // The api.js mocks are module-level vi.fn()s, so their call history has to be
  // reset explicitly — `restoreMocks` only covers spies.
  vi.clearAllMocks();
  window.PushManager = function PushManager() {};
  installNotification();
});

afterEach(() => {
  delete navigator.serviceWorker;
  delete window.PushManager;
  delete window.Notification;
  delete globalThis.Notification;
});

describe("pushSupported", () => {
  it("is false without a PushManager", () => {
    navigator.serviceWorker = {};
    delete window.PushManager;
    expect(pushSupported()).toBe(false);
  });

  it("is true when all three APIs are present", () => {
    installRegistration();
    expect(pushSupported()).toBe(true);
  });
});

describe("permission", () => {
  it("reports the browser's current state", () => {
    installNotification("denied");
    expect(permission()).toBe("denied");
  });

  it("reports unsupported when there is no Notification API", () => {
    delete window.Notification;
    delete globalThis.Notification;
    expect(permission()).toBe("unsupported");
  });
});

describe("urlBase64ToUint8Array", () => {
  it("decodes an unpadded base64url VAPID key to 65 raw bytes", () => {
    const bytes = urlBase64ToUint8Array(VAPID_KEY);
    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(bytes.length).toBe(65);
    expect(bytes[0]).toBe(0x04); // uncompressed point marker
  });
});

describe("fetchPushConfig", () => {
  it("passes the server's config through", async () => {
    apiGet.mockResolvedValue({ enabled: true, public_key: VAPID_KEY });
    expect(await fetchPushConfig()).toEqual({ enabled: true, public_key: VAPID_KEY });
  });

  it("reports disabled rather than throwing when the request fails", async () => {
    // Push is an enhancement; a failure here must not break the Settings screen.
    apiGet.mockRejectedValue(new Error("offline"));
    expect(await fetchPushConfig()).toEqual({ enabled: false, public_key: null });
  });
});

describe("currentSubscription", () => {
  it("returns null when no service worker is registered", async () => {
    navigator.serviceWorker = { getRegistration: vi.fn().mockResolvedValue(undefined) };
    expect(await currentSubscription()).toBeNull();
  });

  it("returns the browser's existing subscription", async () => {
    const sub = fakeSubscription();
    installRegistration({ subscription: sub });
    expect(await currentSubscription()).toBe(sub);
  });
});

describe("enablePush", () => {
  it("subscribes with the raw VAPID key and registers it with the backend", async () => {
    const registration = installRegistration();
    apiSend.mockResolvedValue({ id: 1 });

    await enablePush(VAPID_KEY);

    const args = registration.pushManager.subscribe.mock.calls[0][0];
    expect(args.userVisibleOnly).toBe(true);
    expect(args.applicationServerKey).toBeInstanceOf(Uint8Array);
    expect(apiSend).toHaveBeenCalledWith("/push/subscriptions", "POST", expect.objectContaining({
      endpoint: "https://push.example.com/send/abc",
      keys: { p256dh: "p", auth: "a" },
    }));
  });

  it("explains that push needs the built app when no worker is registered", async () => {
    // The dev server registers none, which is the case people hit first.
    navigator.serviceWorker = { getRegistration: vi.fn().mockResolvedValue(undefined) };
    await expect(enablePush(VAPID_KEY)).rejects.toThrow(/installed app/);
  });

  it("refuses without a server key", async () => {
    installRegistration();
    await expect(enablePush(null)).rejects.toThrow(/no push keys/);
  });

  it("reports a blocked site when permission is denied", async () => {
    installRegistration();
    installNotification("default", "denied");
    await expect(enablePush(VAPID_KEY)).rejects.toThrow(/blocked/i);
  });

  it("does not subscribe at all if permission is refused", async () => {
    const registration = installRegistration();
    installNotification("default", "default");
    await expect(enablePush(VAPID_KEY)).rejects.toThrow(/wasn't granted/);
    expect(registration.pushManager.subscribe).not.toHaveBeenCalled();
  });

  it("rolls the browser subscription back if the server won't store it", async () => {
    // Otherwise the browser holds a permission grant that yields no notifications.
    const sub = fakeSubscription();
    installRegistration({ subscribeResult: sub });
    apiSend.mockRejectedValue(new Error("500"));

    await expect(enablePush(VAPID_KEY)).rejects.toThrow("500");
    expect(sub.unsubscribe).toHaveBeenCalled();
  });
});

describe("disablePush", () => {
  it("deletes the server row before unsubscribing the browser", async () => {
    const order = [];
    const sub = fakeSubscription("https://push.example.com/send/xyz");
    sub.unsubscribe = vi.fn(async () => { order.push("browser"); return true; });
    apiDelete.mockImplementation(async () => { order.push("server"); });
    installRegistration({ subscription: sub });

    expect(await disablePush()).toBe(true);
    // Reversed, a failed request would leave a row nothing can receive on.
    expect(order).toEqual(["server", "browser"]);
    expect(apiDelete).toHaveBeenCalledWith(
      "/push/subscriptions?endpoint=https%3A%2F%2Fpush.example.com%2Fsend%2Fxyz"
    );
  });

  it("treats an already-deleted row as success", async () => {
    const sub = fakeSubscription();
    installRegistration({ subscription: sub });
    apiDelete.mockRejectedValue(Object.assign(new Error("gone"), { status: 404 }));

    expect(await disablePush()).toBe(true);
    expect(sub.unsubscribe).toHaveBeenCalled();
  });

  it("keeps the browser subscribed when the server errors for another reason", async () => {
    const sub = fakeSubscription();
    installRegistration({ subscription: sub });
    apiDelete.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));

    await expect(disablePush()).rejects.toThrow("boom");
    expect(sub.unsubscribe).not.toHaveBeenCalled();
  });

  it("is a no-op when this browser has no subscription", async () => {
    installRegistration({ subscription: null });
    expect(await disablePush()).toBe(false);
    expect(apiDelete).not.toHaveBeenCalled();
  });
});
