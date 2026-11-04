import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// kiosk hardening: no context menu, no pinch/double-tap zoom, no text selection
for (const ev of ["contextmenu", "gesturestart", "dblclick"]) {
  document.addEventListener(ev, (e) => e.preventDefault(), { passive: false });
}
document.addEventListener("touchmove", (e) => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false });

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
