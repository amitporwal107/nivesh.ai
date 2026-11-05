/** Approvals — placeholder until the screen is built (see docs/autodesk/design/prototype/TD*.dc.html). */
import { screenById, screenNo } from "../nav";
import { ScreenHeader } from "../ui";

export default function ApprovalsScreen() {
  const def = screenById("approvals");
  return (
    <div data-testid="screen-approvals" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <ScreenHeader eyebrow={`${screenNo("approvals")} · ${def.label}`} title={def.label} />
    </div>
  );
}
