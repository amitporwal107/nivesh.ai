/** Simulator — placeholder until the screen is built (see docs/autodesk/design/prototype/TD*.dc.html). */
import { screenById, screenNo } from "../nav";
import { ScreenHeader } from "../ui";

export default function SimulatorScreen() {
  const def = screenById("sim");
  return (
    <div data-testid="screen-sim" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <ScreenHeader eyebrow={`${screenNo("sim")} · ${def.label}`} title={def.label} />
    </div>
  );
}
