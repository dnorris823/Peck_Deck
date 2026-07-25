import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { registerServiceWorker } from "./registerSW.js";
import "./styles.css";

createRoot(document.getElementById("root")).render(<App />);

// After first paint — the worker only matters for the *next* visit, so it must
// never delay this one. No-ops in dev (see registerSW.js).
window.addEventListener("load", () => { registerServiceWorker(); });
