import React from "react";
import V4Router from "./navigation/V4Router";
import "./theme/fonts.css";
import "./theme/reset.css";
import "./theme/tokens.css";

/**
 * V4App — root of the V4 redesign. The `.v4` class scopes every token and style.
 * Mounted by App.js at `/v4/*` with BrowserRouter basename="/v4".
 */
export default function V4App() {
  return (
    <div className="v4">
      <V4Router />
    </div>
  );
}
