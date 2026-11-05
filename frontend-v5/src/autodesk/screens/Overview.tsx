/** Overview — placeholder until the screen is built (see docs/autodesk/design/prototype/TD*.dc.html). */
import { screenById, screenNo } from "../nav";
import { ScreenHeader } from "../ui";

export default function OverviewScreen() {
  const def = screenById("overview");
  return (
    <div data-testid="screen-overview" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <ScreenHeader eyebrow={`${screenNo("overview")} · ${def.label}`} title={def.label} />
    </div>
  );
}
