/** Agents — placeholder until the screen is built (see docs/autodesk/design/prototype/TD*.dc.html). */
import { screenById, screenNo } from "../nav";
import { ScreenHeader } from "../ui";

export default function AgentsScreen() {
  const def = screenById("agents");
  return (
    <div data-testid="screen-agents" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <ScreenHeader eyebrow={`${screenNo("agents")} · ${def.label}`} title={def.label} />
    </div>
  );
}
