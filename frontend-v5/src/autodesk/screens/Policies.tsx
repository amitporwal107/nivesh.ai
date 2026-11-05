/** Policies — placeholder until the screen is built (see docs/autodesk/design/prototype/TD*.dc.html). */
import { screenById, screenNo } from "../nav";
import { ScreenHeader } from "../ui";

export default function PoliciesScreen() {
  const def = screenById("policies");
  return (
    <div data-testid="screen-policies" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <ScreenHeader eyebrow={`${screenNo("policies")} · ${def.label}`} title={def.label} />
    </div>
  );
}
