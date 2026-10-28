// Offline banner. When the connection drops, the page that is already loaded
// keeps working, so the app needs to say it is not live and offer a retry.
import React, { useEffect, useState } from "react";

import { Icon } from "./Icon.jsx";

/** Whether the browser thinks it has a connection. */
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
 * Shown while the browser is offline. Deliberately a banner and not a blocking
 * error: the content underneath is real, just possibly not current.
 */
export function OfflineBanner({ offline = false, loading, onRetry }) {
  if (!offline) return null;
  return (
    <div className="offline-banner" role="status">
      <Icon name="device" className="offline-banner-icon" />
      <span>
        <strong>You're offline</strong> — showing the last data this page loaded.
      </span>
      <button className="btn ghost sm offline-retry" onClick={onRetry} disabled={loading}>
        {loading ? "Retrying…" : "Retry"}
      </button>
    </div>
  );
}
