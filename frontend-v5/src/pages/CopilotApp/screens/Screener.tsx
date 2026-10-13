import { useState, type CSSProperties, type FormEvent } from "react";
import {
  PRIMITIVE_BY_KEY, PRIMITIVE_GROUPS, SCREEN_TEMPLATES, compileScreenQuery,
  type BuilderCondition, type ScreenTemplate,
} from "@/components/chat/screenerPrimitives";
import {
  useCreateScreener, useDeleteScreener, useScreeners, useUpdateScreener, type SavedScreener,
} from "@/hooks/use-screeners";
import {
  Btn, EmptyBlock, Footnote, LoadingBlock, NotConnected, Screen, ScreenHeader, Section, fmtDate,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { AskPill, FilterChips, LoadError, type ChipItem } from "./markets/parts";

type Bucket = "" | "large" | "mid" | "small";

const BUCKETS: ChipItem<Bucket | "any">[] = [
  { key: "any", label: "Any size" },
  { key: "large", label: "Large cap" },
  { key: "mid", label: "Mid cap" },
  { key: "small", label: "Small cap" },
];

const field: CSSProperties = {
  padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)",
  color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13, minWidth: 0,
};

let uid = 0;
function newRule(key = "roe", value = ""): BuilderCondition {
  uid += 1;
  return { id: uid, key, op: PRIMITIVE_BY_KEY[key]?.op ?? "over", value };
}

function asBucket(b: string | undefined): Bucket {
  return b === "large" || b === "mid" || b === "small" ? b : "";
}

/**
 * Screener — build a rule list from the screening metrics the data platform
 * carries, run it in the Copilot, and keep screens you want to reuse.
 * Design: design/nivesh-copilot/NVTools.dc.html (tool === "screener").
 *
 * Running a screen hands the compiled query to the Copilot (the same string the
 * current chat composer sends); the matches are returned in the thread. Saved
 * screens are the user's own, from /api/screeners.
 */
export default function ScreenerScreen() {
  const { ask, mobile } = useCopilotShell();
  const [describe, setDescribe] = useState("");
  const [bucket, setBucket] = useState<Bucket>("");
  const [rules, setRules] = useState<BuilderCondition[]>(() => [newRule("roe"), newRule("pe")]);
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [preset, setPreset] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const saved = useScreeners();
  const createScreen = useCreateScreener();
  const updateScreen = useUpdateScreener();
  const deleteScreen = useDeleteScreener();

  const query = compileScreenQuery(rules, bucket || undefined);
  const canRun = query.length > 0;
  const saving = createScreen.isPending || updateScreen.isPending;
  const saveError = createScreen.error ?? updateScreen.error;

  const touch = () => setPreset(null);
  const setRule = (id: number, patch: Partial<BuilderCondition>) => {
    touch();
    setRules((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };
  const changeMetric = (id: number, key: string) => setRule(id, { key, op: PRIMITIVE_BY_KEY[key]?.op ?? "over" });
  const addRule = () => { touch(); setRules((rs) => [...rs, newRule()]); };
  const removeRule = (id: number) => { touch(); setRules((rs) => (rs.length > 1 ? rs.filter((r) => r.id !== id) : rs)); };

  const reset = () => {
    setBucket("");
    setRules([newRule("roe")]);
    setName("");
    setEditingId(null);
    setPreset(null);
  };

  /** A template becomes a fresh, unsaved rule list the user can change, run or save. */
  const loadTemplate = (t: ScreenTemplate) => {
    setRules(t.conds.map((c) => ({ ...newRule(c.key, c.value), op: c.op })));
    setBucket(asBucket(t.bucket));
    setName(t.name);
    setEditingId(null);
    setPreset(t.name);
  };

  /** A saved screen goes back into the rules for viewing or editing. */
  const loadSaved = (s: SavedScreener) => {
    const mapped = s.conditions
      .filter((c) => PRIMITIVE_BY_KEY[c.key] && !PRIMITIVE_BY_KEY[c.key].bucket)
      .map((c) => ({ ...newRule(c.key, c.value), op: c.op === "under" ? "under" as const : "over" as const }));
    setRules(mapped.length ? mapped : [newRule()]);
    setBucket(asBucket(s.bucket));
    setName(s.name);
    setEditingId(s.screener_id);
    setPreset(null);
  };

  const save = () => {
    if (!canRun || !name.trim() || saving) return;
    const body = {
      name: name.trim(),
      query,
      conditions: rules.filter((r) => r.value.trim() !== "").map((r) => ({ key: r.key, op: r.op, value: r.value.trim() })),
      bucket,
    };
    if (editingId) updateScreen.mutate({ id: editingId, body });
    else createScreen.mutate(body, { onSuccess: (s) => setEditingId(s.screener_id) });
  };

  const remove = (id: string) => {
    if (editingId === id) reset();
    setConfirmDelete(null);
    deleteScreen.mutate(id);
  };

  const onDescribe = (e: FormEvent) => {
    e.preventDefault();
    const text = describe.trim();
    if (!text) return;
    ask(/^screen\b/i.test(text) ? text : `Screen for ${text}`);
  };

  return (
    <Screen testId="screen-tool-screener">
      <ScreenHeader
        eyebrow="Stock screener · end-of-day data"
        pills={<AskPill query="Which sectors are showing improving relative strength, and what is breaking out?" testId="screener-ask" />}
        title="Find stocks by rule"
        sub="Describe what you want, start from a template, or build the rules yourself. The Copilot runs the screen and returns the matches in the thread."
      />

      {/* ── describe ── */}
      <form onSubmit={onDescribe} className="cp-card flex flex-wrap items-center" style={{ gap: 10, padding: "12px 14px", borderColor: "var(--mint-line)" }}>
        <label htmlFor="screener-describe" className="cp-mono-note" style={{ color: "var(--mint)", letterSpacing: "0.1em" }}>Describe</label>
        <input
          id="screener-describe"
          data-testid="screener-describe"
          value={describe}
          onChange={(e) => setDescribe(e.target.value)}
          placeholder="“Profitable midcaps with rising FII stake and low debt”"
          autoComplete="off"
          style={{ flex: "1 1 220px", minWidth: 0, border: 0, outline: "none", background: "none", fontSize: 14, color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
        />
        <button
          type="submit"
          disabled={!describe.trim()}
          data-testid="screener-describe-submit"
          style={{ padding: 0, border: 0, background: "none", fontSize: 13, color: "var(--mint)", cursor: describe.trim() ? "pointer" : "not-allowed", opacity: describe.trim() ? 1 : 0.5, fontFamily: "var(--sans)" }}
        >
          Screen in Copilot ›
        </button>
      </form>

      {/* ── templates ── */}
      <div className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Start from a template</span>
        <div className="flex flex-wrap" style={{ gap: 8 }} data-testid="screener-presets">
          {SCREEN_TEMPLATES.map((t) => (
            <button
              key={t.name}
              type="button"
              aria-pressed={preset === t.name}
              data-testid="screener-preset"
              onClick={() => loadTemplate(t)}
              className="cp-card flex flex-col"
              style={{ gap: 2, padding: "10px 14px", borderRadius: 12, cursor: "pointer", textAlign: "left", color: "var(--cp-ink)", fontFamily: "var(--sans)", flex: mobile ? "1 1 100%" : "0 1 auto", borderColor: preset === t.name ? "var(--mint-line)" : undefined }}
            >
              <span style={{ fontSize: 13, fontWeight: 500 }}>{t.name}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-3)" }}>{t.hint} · {t.conds.length} rules</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── rules ── */}
      <Section title={editingId ? "Rules · editing a saved screen" : "Rules"} note={`${rules.filter((r) => r.value.trim() !== "").length} set`}>
        <div className="flex flex-col" style={{ gap: 14 }}>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <span className="cp-mono-note">Universe</span>
            <FilterChips
              items={BUCKETS}
              value={bucket === "" ? "any" : bucket}
              onChange={(b) => { touch(); setBucket(b === "any" ? "" : b); }}
              label="Market-cap universe"
              idPrefix="screener-bucket"
            />
          </div>

          <div className="flex flex-col" style={{ gap: 8 }} data-testid="screener-rules">
            {rules.map((r, i) => {
              const p = PRIMITIVE_BY_KEY[r.key];
              return (
                <div key={r.id} className="flex flex-wrap items-center" style={{ gap: 8 }} data-testid="screener-rule">
                  <select
                    aria-label={`Rule ${i + 1} metric`}
                    value={r.key}
                    onChange={(e) => changeMetric(r.id, e.target.value)}
                    style={{ ...field, flex: "1 1 180px" }}
                    data-testid="screener-rule-metric"
                  >
                    {PRIMITIVE_GROUPS.map((g) => (
                      <optgroup key={g.cat} label={g.cat}>
                        {g.items.filter((it) => !it.bucket).map((it) => <option key={it.key} value={it.key}>{it.label}</option>)}
                      </optgroup>
                    ))}
                  </select>
                  <select
                    aria-label={`Rule ${i + 1} comparison`}
                    value={r.op}
                    onChange={(e) => setRule(r.id, { op: e.target.value === "under" ? "under" : "over" })}
                    style={field}
                    data-testid="screener-rule-op"
                  >
                    <option value="over">over</option>
                    <option value="under">under</option>
                  </select>
                  <span className="flex items-center" style={{ gap: 6 }}>
                    <input
                      aria-label={`Rule ${i + 1} value${p?.tag ? ` (${p.tag})` : ""}`}
                      type="number"
                      inputMode="decimal"
                      value={r.value}
                      onChange={(e) => setRule(r.id, { value: e.target.value })}
                      placeholder="value"
                      style={{ ...field, width: 96 }}
                      className="cp-num"
                      data-testid="screener-rule-value"
                    />
                    {p?.tag && <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)", textTransform: "none" }}>{p.tag}</span>}
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove rule ${i + 1}`}
                    title={rules.length === 1 ? "A screen needs at least one rule" : "Remove this rule"}
                    disabled={rules.length === 1}
                    onClick={() => removeRule(r.id)}
                    style={{ padding: "4px 8px", border: 0, background: "none", fontSize: 16, lineHeight: 1, color: "var(--cp-ink-3)", cursor: rules.length === 1 ? "not-allowed" : "pointer", opacity: rules.length === 1 ? 0.4 : 1 }}
                  >
                    ×
                  </button>
                </div>
              );
            })}
            <button
              type="button"
              onClick={addRule}
              data-testid="screener-add-rule"
              style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", fontSize: 13, color: "var(--mint)", cursor: "pointer", fontFamily: "var(--sans)" }}
            >
              ＋ Add rule
            </button>
          </div>

          <div className="flex flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)" }}>
            <span className="cp-mono-note">Query sent to the Copilot</span>
            <code data-testid="screener-query" style={{ fontFamily: "var(--mono)", fontSize: 12, lineHeight: 1.5, color: canRun ? "var(--cp-ink)" : "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
              {canRun ? query : "Give at least one rule a value, or pick a market-cap universe."}
            </code>
          </div>

          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <Btn variant="primary" disabled={!canRun} onClick={() => ask(query)} data-testid="screener-run">Run screen in Copilot ›</Btn>
            <Btn variant="ghost" onClick={reset}>{editingId ? "New screen" : "Reset"}</Btn>
            <span style={{ flex: "1 1 12px" }} />
            <label htmlFor="screener-name" className="sr-only">Name for this screen</label>
            <input
              id="screener-name"
              data-testid="screener-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={editingId ? "Screen name" : "Save this screen as…"}
              maxLength={80}
              autoComplete="off"
              style={{ ...field, flex: "1 1 180px" }}
            />
            <Btn disabled={!canRun || !name.trim() || saving} onClick={save} data-testid="screener-save">
              {saving ? "Saving…" : editingId ? "Update" : "Save"}
            </Btn>
          </div>
          {saveError && <LoadError title="The screen wasn’t saved" error={saveError} />}
        </div>
      </Section>

      {/* ── saved screens ── */}
      <div className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Your saved screens</span>
        {saved.isPending ? (
          <LoadingBlock label="Loading saved screens" />
        ) : saved.isError ? (
          <LoadError title="Saved screens didn’t load" error={saved.error} onRetry={() => saved.refetch()} />
        ) : saved.data.length === 0 ? (
          <EmptyBlock title="No saved screens yet" body="Name a rule list above and save it to run it again later." />
        ) : (
          <div className="cp-card flex flex-col" data-testid="screener-saved">
            {saved.data.map((s) => (
              <div
                key={s.screener_id}
                data-testid="screener-saved-row"
                className="flex flex-wrap items-center"
                style={{ gap: "8px 12px", padding: "12px 16px", borderBottom: "1px solid var(--cp-line)", background: editingId === s.screener_id ? "var(--mint-soft)" : undefined }}
              >
                <div className="flex min-w-0 flex-col" style={{ flex: "1 1 220px", gap: 3 }}>
                  <span style={{ fontSize: 14, fontWeight: 500 }} data-testid="screener-saved-name">{s.name}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{s.query}</span>
                  {s.updated_at && <span className="cp-mono-note">Saved {fmtDate(s.updated_at)}</span>}
                </div>
                <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
                  <Btn onClick={() => ask(s.query)} data-testid="screener-saved-run" style={{ padding: "6px 10px", fontSize: 12 }}>Run ›</Btn>
                  <Btn variant="ghost" onClick={() => loadSaved(s)} data-testid="screener-saved-edit" style={{ padding: "6px 10px", fontSize: 12 }}>Edit</Btn>
                  {confirmDelete === s.screener_id ? (
                    <>
                      <Btn onClick={() => remove(s.screener_id)} data-testid="screener-saved-delete-confirm" style={{ padding: "6px 10px", fontSize: 12, color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}>Delete it</Btn>
                      <Btn variant="ghost" onClick={() => setConfirmDelete(null)} style={{ padding: "6px 10px", fontSize: 12 }}>Keep</Btn>
                    </>
                  ) : (
                    <Btn variant="ghost" onClick={() => setConfirmDelete(s.screener_id)} disabled={deleteScreen.isPending} data-testid="screener-saved-delete" style={{ padding: "6px 10px", fontSize: 12 }}>Delete</Btn>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {deleteScreen.isError && <LoadError title="The screen wasn’t deleted" error={deleteScreen.error} />}
      </div>

      {/* ── results ── */}
      <NotConnected
        testId="screener-results-nc"
        title="Matches open in the Copilot thread"
        body="The design shows the matching stocks in a table on this page. The product runs screens only inside the Copilot today, so the matches, with their sector, market cap and ratios, come back in the thread when you run a screen."
        needs={[
          "An endpoint that takes this rule list and returns the matching stocks with a total count",
          "Match counts for each template, to show beside its name",
        ]}
        action={<Btn variant="primary" disabled={!canRun} onClick={() => ask(query)}>Run screen in Copilot ›</Btn>}
      />

      <Footnote>End-of-day data · screen matches are candidates, not recommendations</Footnote>
    </Screen>
  );
}
