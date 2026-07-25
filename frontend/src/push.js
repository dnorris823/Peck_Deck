// Web push opt-in — FLEDGE Phase 7 (browser side).
//
// The fourth notification channel next to email and SMS, and the only one that
// is per-*browser* rather than per-account: the subscription belongs to this
// installation, so the toggle in Settings reflects what this browser has done,
// not a column on the user row.
//
// Every function here degrades to "unavailable" rather than throwing on a
// browser (or a build) that can't do push — notably the dev server, which has no
// service worker registered at all.

import { apiDelete, apiGet, apiSend } from "./api.js";

/** Does this browser have the three APIs push needs? */
export function pushSupported() {
  return (
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator &&
    typeof window !== "undefined" &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function permission() {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission; // "default" | "granted" | "denied"
}

/**
 * The active service worker registration, or null.
 *
 * Deliberately `getRegistration()` and not `navigator.serviceWorker.ready`:
 * `ready` never settles when nothing is registered, which would hang the
 * Settings screen forever in dev.
 */
async function getRegistration() {
  if (!pushSupported()) return null;
  try {
    return (await navigator.serviceWorker.getRegistration("/")) || null;
  } catch {
    return null;
  }
}

/** The server's VAPID key + whether push is configured at all. */
export async function fetchPushConfig() {
  try {
    return await apiGet("/push/config");
  } catch {
    // Push is an enhancement; a failure here must not break Settings.
    return { enabled: false, public_key: null };
  }
}

/** Whether this browser currently holds a subscription. */
export async function currentSubscription() {
  const registration = await getRegistration();
  if (!registration) return null;
  try {
    return await registration.pushManager.getSubscription();
  } catch {
    return null;
  }
}

/**
 * `applicationServerKey` must be raw bytes; the API serves the key base64url,
 * which is also what the browser echoes back inside the subscription.
 */
export function urlBase64ToUint8Array(base64) {
  const padded = base64.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/**
 * Ask for permission, subscribe, and register the subscription with the backend.
 *
 * Throws with a message meant for display. The order matters: permission first
 * (so a refusal costs nothing), then the browser subscription, then the server
 * row — a row without a live browser subscription would be pushed to forever.
 */
export async function enablePush(publicKey) {
  const registration = await getRegistration();
  if (!registration) {
    throw new Error(
      "Push needs the installed app. Add Peck Deck to your home screen, " +
      "or run a production build (npm run build && npm run preview)."
    );
  }
  if (!publicKey) throw new Error("This server has no push keys configured.");

  const granted = await Notification.requestPermission();
  if (granted !== "granted") {
    throw new Error(
      granted === "denied"
        ? "Notifications are blocked for this site in your browser settings."
        : "Notification permission wasn't granted."
    );
  }

  const subscription = await registration.pushManager.subscribe({
    // Required by Chrome: every push must result in a visible notification.
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(publicKey),
  });

  const json = subscription.toJSON();
  try {
    await apiSend("/push/subscriptions", "POST", {
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      user_agent: navigator.userAgent,
    });
  } catch (err) {
    // Don't leave the browser subscribed to a server that never stored it —
    // it would then hold a permission grant that produces no notifications.
    await subscription.unsubscribe().catch(() => {});
    throw err;
  }
  return subscription;
}

/**
 * Unsubscribe this browser and forget the row.
 *
 * The server row goes first: if the browser unsubscribed first and the request
 * then failed, the row would survive with an endpoint nothing can receive on.
 * A 404 is success — the row was already gone.
 */
export async function disablePush() {
  const subscription = await currentSubscription();
  if (!subscription) return false;

  try {
    await apiDelete(`/push/subscriptions?endpoint=${encodeURIComponent(subscription.endpoint)}`);
  } catch (err) {
    if (err.status !== 404) throw err;
  }
  await subscription.unsubscribe();
  return true;
}
