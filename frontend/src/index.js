import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import { bootstrapNative } from "@/native/bootstrap";
import { installContentProtection } from "@/security/contentProtection";

bootstrapNative();

// Copy/screenshot deterrents for prod (see module header for honest scope —
// this raises friction, it does not truly prevent capture).
installContentProtection();

// Suppress uninformative cross-origin "Script error." events that trigger the
// CRA dev-overlay on some mobile browsers (Samsung Internet, older Chrome).
// Keep real errors visible — we only drop the generic stripped-CORS ones.
if (typeof window !== "undefined") {
  window.addEventListener(
    "error",
    (e) => {
      if (e && e.message === "Script error." && !e.filename) {
        e.preventDefault();
        e.stopImmediatePropagation();
        return false;
      }
    },
    true
  );
  window.addEventListener("unhandledrejection", (e) => {
    const msg = String(e?.reason?.message || e?.reason || "");
    // Axios 401s from /auth/me on unauthenticated landing are expected.
    if (msg.includes("401") || msg.includes("Network Error")) {
      e.preventDefault();
    }
  });
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
