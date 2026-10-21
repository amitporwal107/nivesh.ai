import RiskPage from "@/pages/Risk";
import { LegacyFrame } from "./LegacyFrame";

/** Risk dashboard — the original v5 screen, mounted as it is. */
export default function RiskScreen() {
  return (
    <LegacyFrame testId="screen-tool-risk">
      <RiskPage />
    </LegacyFrame>
  );
}
