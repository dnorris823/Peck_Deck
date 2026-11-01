// Tier 2's pause state, read from GET /tier2. The inference server pauses
// itself while a game runs, and the owner can pause it from the Feeders page.
import { useCallback, useEffect, useState } from "react";
import { fetchTier2, setTier2Paused } from "./data.js";

// Home and the feeder card say this instead of the Tier 2 down warning.
export const TIER2_PAUSED = "Tier 2 paused for gaming";

const POLL_MS = 60_000;
// While the model loads, so the switch shows "on" soon after it is.
const LOADING_POLL_MS = 2_000;

export function isTier2Paused(state) {
  return state === "paused_manual" || state === "paused_game";
}

/** The switch's one line for each state. */
export function tier2Label(state) {
  switch (state) {
    case "ready": return "On. The gaming PC names every capture.";
    case "loading": return "Loading the model…";
    case "paused_manual": return "Paused. The Pi names birds on its own until you turn it on.";
    case "paused_game": return "Paused, a game is running";
    case "failed": return "On, but the model did not load. Turn it off and on to try again.";
    case "offline": return "The gaming PC is not answering.";
    default: return "Checking…";
  }
}

/**
 * `{ status, set, error }`. `status` is the last GET /tier2 body, or null
 * before the first answer or after a failed read. `set(paused)` sends the
 * switch, then reads the state again, fast while the model loads.
 */
export function useTier2() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  // Bumped by `set`, which restarts the poll.
  const [kick, setKick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer;
    async function poll() {
      let next = null;
      try {
        next = await fetchTier2();
      } catch {
        // The page works without it. The Tier 2 down warning still shows.
      }
      if (!alive) return;
      setStatus(next);
      timer = setTimeout(poll, next?.state === "loading" ? LOADING_POLL_MS : POLL_MS);
    }
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [kick]);

  const set = useCallback(async (paused) => {
    setError(null);
    try {
      setStatus(await setTier2Paused(paused));
      setKick(k => k + 1);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  return { status, set, error };
}
