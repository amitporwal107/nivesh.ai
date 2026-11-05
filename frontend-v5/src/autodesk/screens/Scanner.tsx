/** Scanner — placeholder until the screen is built (see docs/autodesk/design/prototype/TD*.dc.html). */
import { screenById, screenNo } from "../nav";
import { ScreenHeader } from "../ui";

export default function ScannerScreen() {
  const def = screenById("scanner");
  return (
    <div data-testid="screen-scanner" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <ScreenHeader eyebrow={`${screenNo("scanner")} · ${def.label}`} title={def.label} />
    </div>
  );
}
