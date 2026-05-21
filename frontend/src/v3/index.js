import React from "react";
import V3Router from "./navigation/V3Router";
import "./theme/tokens.css";
import "./theme/reset.css";
import "./theme/fonts.css";

/**
 * V3App — root of the V3 redesign. The `.v3` class scopes every token and style.
 * Mounted by App.js at `/v3/*` and inherits the existing BrowserRouter (basename="/v2").
 */
export default function V3App() {
  return (
    <div className="v3">
      <V3Router />
    </div>
  );
}
