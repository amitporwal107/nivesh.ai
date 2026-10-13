import TaxPage from "@/pages/Tax";
import { LegacyFrame } from "./LegacyFrame";

/** Tax dashboard — the original v5 screen, mounted as it is. */
export default function TaxScreen() {
  return (
    <LegacyFrame testId="screen-tool-tax">
      <TaxPage />
    </LegacyFrame>
  );
}
