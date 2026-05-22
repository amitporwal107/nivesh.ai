import React from "react";
import Exposure from "./Exposure";

// Legacy route /v3/portfolio/diversification — preserved as a thin wrapper so
// existing bookmarks and internal links keep working. New canonical route is
// /v3/portfolio/exposure?tab=diversification.
export default function Diversification() {
  return <Exposure defaultTab="diversification" />;
}
