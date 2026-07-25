// Offline banner + pull-to-refresh — FLEDGE Phase 7.
//
// Two mobile affordances that only make sense together: when the connection
// drops the app keeps showing cached content, so it needs to (a) say so, and
// (b) offer a way to try again that feels native on a phone.
import React, { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "./Icon.jsx";
import { fmtRelative } from "./data.js";

/**
 * Whether the browser thinks it has a connection.
 *
 * Needed on top of the `stale` flag because the two failure modes look different
 * from inside the app: with the service worker installed an offline load *
 * succeeds* — it is answered from the cache — so nothing in the data layer knows
 * anything is wrong. `navigator.onLine` is what notices.
 */
export function useOnline() {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" || navigator.onLine !== false
  );

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  return online;
}

/**
 * Shown when the visible data isn't known to be live — either the browser is
 * offline, or a refresh failed and the offline snapshot is what's on screen.
 * Deliberately a banner and not a blocking error: the content underneath is
 * real, just possibly not current.
 */
export function OfflineBanner({ stale, offline = false, loading, onRetry }) {
  if (!stale && !offline) return null;
  return (
    <div className="offline-banner" role="status">
      <Icon name="device" className="offline-banner-icon" />
      <span>
        <strong>{offline ? "You're offline" : "Showing saved data"}</strong>
        {stale ? (
          <> — last updated {fmtRelative(new Date(stale.savedAt))}.</>
        ) : (
          <> — showing the last data this device loaded.</>
        )}
      </span>
      <button className="btn ghost sm offline-retry" onClick={onRetry} disabled={loading}>
        {loading ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}

// How far the finger must travel past the top of the page before a release
// triggers a refresh. Roughly the height of the indicator, so the gesture only
// fires once it has visibly committed.
const THRESHOLD = 72;
// Past this the indicator stops following the finger, so a long drag doesn't
// push the whole page down.
const MAX_PULL = 110;

/**
 * Native-feeling pull-to-refresh for touch devices.
 *
 * Implemented by hand rather than relying on the browser's own gesture: that one
 * reloads the *document*, which throws away the React tree, the JWT-authenticated
 * requests in flight, and the current screen — for what is only a data refresh.
 * `overscroll-behavior-y: contain` on <body> (styles.css) suppresses the native
 * version so the two can't both fire.
 *
 * Only arms when the page is already scrolled to the top, so it can never
 * hijack a normal upward scroll mid-list.
 */
export function usePullToRefresh(onRefresh, { busy = false, threshold = THRESHOLD } = {}) {
  const [pull, setPull] = useState(0);
  const startY = useRef(null);
  const armed = useRef(false);

  const scrollTop = () =>
    window.scrollY || document.documentElement.scrollTop || 0;

  useEffect(() => {
    function onTouchStart(e) {
      if (e.touches.length !== 1 || busy) return;
      armed.current = scrollTop() <= 0;
      startY.current = e.touches[0].clientY;
    }

    function onTouchMove(e) {
      if (!armed.current || startY.current == null) return;
      const delta = e.touches[0].clientY - startY.current;
      if (delta <= 0) {
        // Dragging up is an ordinary scroll — disarm so this gesture is over.
        armed.current = false;
        setPull(0);
        return;
      }
      // Resistance: the pull slows as it grows, which is what makes the
      // threshold findable by feel.
      setPull(Math.min(MAX_PULL, delta * 0.5));
    }

    function onTouchEnd() {
      const shouldRefresh = armed.current && pull >= threshold;
      armed.current = false;
      startY.current = null;
      setPull(0);
      if (shouldRefresh) onRefresh?.();
    }

    // Passive: this never calls preventDefault (overscroll-behavior does that
    // job in CSS), and a non-passive touchmove listener would cost scroll
    // performance on every list in the app.
    const opts = { passive: true };
    window.addEventListener("touchstart", onTouchStart, opts);
    window.addEventListener("touchmove", onTouchMove, opts);
    window.addEventListener("touchend", onTouchEnd, opts);
    window.addEventListener("touchcancel", onTouchEnd, opts);
    return () => {
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [onRefresh, busy, threshold, pull]);

  return { pull, ready: pull >= threshold };
}

/** The indicator the gesture drags into view. Renders nothing when idle. */
export function PullToRefresh({ onRefresh, busy }) {
  const handle = useCallback(() => onRefresh?.(), [onRefresh]);
  const { pull, ready } = usePullToRefresh(handle, { busy });

  if (pull <= 0 && !busy) return null;
  // While a refresh is running the indicator parks at the threshold so the
  // spinner doesn't snap away the instant the finger lifts.
  const offset = busy && pull <= 0 ? THRESHOLD : pull;

  return (
    <div className="ptr" style={{ height: offset }} aria-hidden="true">
      <div className={`ptr-mark ${ready || busy ? "ready" : ""}`}>
        {busy ? "Refreshing…" : ready ? "Release to refresh" : "Pull to refresh"}
      </div>
    </div>
  );
}
