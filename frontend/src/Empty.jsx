// Shared empty-state block — shown when a list/grid has nothing to render, so
// pages never bottom out into blank space. Optional action renders a CTA button.
import React from "react";

export function Empty({ icon = "🪶", title, hint, action }) {
  return (
    <div className="empty" role="status">
      <div className="empty-mark" aria-hidden="true">{icon}</div>
      <div className="empty-title">{title}</div>
      {hint && <div className="empty-hint">{hint}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}
