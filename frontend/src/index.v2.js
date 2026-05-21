// V2 bundle entry — the original Nivesh V2 app. Identical to the legacy
// src/index.js logic, just renamed so src/index.js can dispatch between
// REACT_APP_BUNDLE_TARGET=v2 and =v3 at build time.

import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import { bootstrapNative } from "@/native/bootstrap";

bootstrapNative();

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
    if (msg.includes("401") || msg.includes("Network Error")) {
      e.preventDefault();
    }
  });
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
