import SimulationLabScreen from "@/pages/Research/SimulationLabScreen";
// The original screen's inline styles use the colour aliases (--c-ink…, --c-line)
// that research.css defines on .research-screen.
import "@/pages/Research/research.css";

/**
 * Simulation lab — the original v5 Research → Lab screen, mounted as it is:
 * the frozen, pre-registered simulation runs of the paper-trade engine (the
 * run, the configuration matrix, data quality, reconciliation, trade by trade).
 *
 *   GET /api/sim-lab/run · /matrix · /trades · /candidates   (backend/routes/sim_lab.py)
 *
 * The API answers 403 to accounts without the sim_lab feature, and the screen
 * then says so; Paper.tsx offers this view only to accounts that have it, the
 * same gate the original Research page uses.
 */
export default function SimulationLab() {
  return (
    <div data-testid="paper-sim-lab" className="research-screen" style={{ margin: "0 -12px", minWidth: 0 }}>
      <SimulationLabScreen />
    </div>
  );
}
