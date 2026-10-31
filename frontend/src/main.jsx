import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { registerServiceWorker } from "./registerSW.js";
import { applyAppearance, loadAppearance } from "./Appearance.jsx";
import "./styles.css";

// Apply the saved theme before the first render, so the app does not paint in
// the default palette and then switch.
applyAppearance(loadAppearance());

createRoot(document.getElementById("root")).render(<App />);

// The app used to keep a copy of the last API payloads here. Drop any left
// behind, because it holds a user's sighting records.
try { localStorage.removeItem("peckdeck_snapshot"); } catch { /* storage blocked */ }

// After first paint — the worker only matters for the *next* visit, so it must
// never delay this one. No-ops in dev (see registerSW.js).
window.addEventListener("load", () => { registerServiceWorker(); });
