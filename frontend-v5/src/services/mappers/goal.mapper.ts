/**
 * Goal mapper — wire Goal → domain Goal.
 *
 * Wire uses rupees-as-number; domain stores paise. Mapper × 100.
 * Adds projected_corpus and sip_gap to currentAmount derivation.
 */
import type { GoalC } from "@/services/contracts/goal.contract";
import type { Goal as DomainGoal } from "@/types/goal";

const ICON_BY_TYPE: Record<string, string> = {
  retirement: "🌴",
  education:  "🎓",
  home:       "🏠",
  emergency:  "🆘",
  wealth:     "📈",
  other:      "🎯",
};

export function mapGoal(c: GoalC): DomainGoal {
  const onTrackPct = c.on_track_pct ?? 0;          // 0..100 from backend
  const progress = onTrackPct / 100;
  const onTrack = onTrackPct >= 70;

  return {
    id: c.goal_id,
    icon: ICON_BY_TYPE[c.goal_type] ?? "🎯",
    name: c.goal_name,
    targetDate: horizonToDate(c.horizon_years),
    targetAmount:  c.target_amount_rs * 100,
    currentAmount: (c.current_corpus_rs ?? 0) * 100,
    monthlySip:    c.monthly_sip_rs * 100,
    onTrack,
    progress,
    message: onTrack
      ? "On track"
      : c.sip_gap_rs && c.sip_gap_rs > 0
        ? `Add ₹${Math.round(c.sip_gap_rs).toLocaleString("en-IN")}/mo`
        : "Needs attention",
  };
}

export function mapGoals(list: GoalC[]): DomainGoal[] {
  return list.map(mapGoal);
}

function horizonToDate(years: number): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() + years);
  return d.toISOString().slice(0, 10);
}
