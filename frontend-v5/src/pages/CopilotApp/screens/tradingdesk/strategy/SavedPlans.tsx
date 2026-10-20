/**
 * Strategy Builder — the user's saved plans (PRD §16.5 lifecycle): newest first, open and delete. A saved plan
 * is a research record that never changes; delete removes only this saved copy ("saved copy only"), never a
 * paper trade or anything at a broker. The route's ownership (404 for another user's plan) and limit (200)
 * messages are shown as the route words them.
 */
import { useState } from "react";
import { StockIcon } from "../../../components/EntityIcon";
import { Btn, ErrorBlock, LoadingBlock, Section, humaniseTag } from "../../../components/ui";
import { fmtDay } from "../../trading/parts";
import { TrustLine } from "../trust";
import { planFailure, useDeletePlan, useSavedPlans } from "./plan-data";
import { STATUS_WORDS, noteStyle } from "./plan-format";
import type { PlanStatus } from "./plan-contract";

export function SavedPlans({ openId, onOpen, onDeleted }: { openId: string | null; onOpen: (id: string, sym: string | null) => void; onDeleted: (id: string) => void }) {
  const q = useSavedPlans();
  const del = useDeletePlan();
  const [confirm, setConfirm] = useState<string | null>(null);
  const [note, setNote] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const doDelete = async (id: string) => {
    setNote(null);
    try {
      const r = await del.mutateAsync(id);
      setConfirm(null);
      onDeleted(id);
      setNote({ tone: "ok", text: r.note ?? "Deleted only your saved copy. Nothing else changed and nothing was sent to a broker." });
    } catch (e) {
      setConfirm(null);
      setNote({ tone: "bad", text: planFailure(e, "Not deleted") });
    }
  };
  return (
    <Section title="Saved plans" note={q.data ? `${q.data.count} of ${q.data.max_saved} allowed` : undefined}>
      <div data-testid="saved-plans" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        {q.isPending && <LoadingBlock label="Loading saved plans" rows={2} />}
        {q.isError && <ErrorBlock title="Saved plans didn’t load" error={q.error} onRetry={() => q.refetch()} />}
        {q.data && q.data.plans.length === 0 && <p data-testid="saved-empty" className="m-0" style={noteStyle}>No saved plans yet. Build a plan and choose “Save this plan”.</p>}
        {q.data && q.data.plans.length > 0 && (
          <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
            {q.data.plans.map((p) => {
              const st = STATUS_WORDS[(p.status as PlanStatus) in STATUS_WORDS ? (p.status as PlanStatus) : "insufficient_data"];
              return (
                <li key={p.id} data-testid={`saved-${p.id}`} data-open={p.id === openId} className="flex flex-wrap items-center" style={{ gap: "6px 12px", padding: "10px 0", borderTop: "1px solid var(--cp-line)" }}>
                  {p.underlying && <StockIcon symbol={p.underlying} size={22} />}
                  <span style={{ fontWeight: 500 }}>{p.underlying ?? "—"}</span>
                  <span style={{ fontSize: 12.5 }}>{humaniseTag(p.direction)} · {humaniseTag(p.horizon)} · {humaniseTag(p.segment)}</span>
                  <span data-testid="saved-status" style={{ fontSize: 12.5 }}><span aria-hidden>{st.glyph} </span>{st.trader}</span>
                  <span className="cp-mono-note">data {fmtDay(p.data_as_of)} · saved {fmtDay(p.saved_at)} · {p.rules_version}</span>
                  <span style={{ flex: 1 }} />
                  <Btn data-testid={`saved-open-${p.id}`} onClick={() => onOpen(p.id, p.underlying)}>Open</Btn>
                  {confirm === p.id ? (
                    <>
                      <span style={noteStyle}>Delete this saved copy only?</span>
                      <Btn data-testid={`saved-confirm-${p.id}`} disabled={del.isPending} onClick={() => doDelete(p.id)}>Yes, delete the saved copy</Btn>
                      <Btn variant="ghost" onClick={() => setConfirm(null)}>Keep</Btn>
                    </>
                  ) : <Btn variant="ghost" data-testid={`saved-delete-${p.id}`} onClick={() => setConfirm(p.id)}>Delete</Btn>}
                </li>
              );
            })}
          </ul>
        )}
        {note && <p data-testid="saved-note" role={note.tone === "bad" ? "alert" : "status"} className="m-0" style={{ fontSize: 13, color: note.tone === "bad" ? "var(--cp-danger)" : "var(--mint)" }}>{note.text}</p>}
        <TrustLine testId="saved-trust" source="Your saved strategy plans" maker="rules" />
      </div>
    </Section>
  );
}
