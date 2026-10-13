import GoalsPage from "@/pages/Goals";
import { LegacyFrame } from "./LegacyFrame";

/** Goals and planning — the original v5 screen, mounted as it is. */
export default function GoalsScreen() {
  return (
    <LegacyFrame testId="screen-tool-goals">
      <GoalsPage />
    </LegacyFrame>
  );
}
