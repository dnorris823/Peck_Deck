// Tier 2's switch on the Feeders page. The owner turns the gaming PC's model
// off and on. Everyone else sees its state.
import React, { useState } from "react";
import { isTier2Paused, tier2Label } from "./tier2.js";

export function Tier2Switch({ tier2, isOwner }) {
  const { status, set, error } = tier2;
  const [busy, setBusy] = useState(false);
  const state = status?.state;
  // Loading counts as on, so the switch does not flick back while it loads.
  const on = state === "ready" || state === "loading" || state === "failed";
  const canSwitch = isOwner && state != null && state !== "offline";

  async function flip() {
    setBusy(true);
    await set(on);
    setBusy(false);
  }

  return (
    <div className="card card-pad tier2-switch">
      <div className="toggle-row">
        <div className="toggle-row-text">
          <div className="toggle-row-title">Tier 2 on the gaming PC</div>
          <div className={`toggle-row-sub${isTier2Paused(state) ? " tier2-paused" : ""}`} role="status">
            {tier2Label(state)}
          </div>
          {error && <div className="toggle-row-sub tier2-error" role="alert">{error}</div>}
        </div>
        {isOwner && (
          <button type="button" className={`toggle ${on ? "on" : ""}`} onClick={flip}
            aria-pressed={on} aria-label="Tier 2 on the gaming PC"
            disabled={!canSwitch || busy} />
        )}
      </div>
    </div>
  );
}
