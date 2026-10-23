/**
 * Bot details — screen 1 of the Strategy Builder config design
 * (docs/STRATEGY_BUILDER_CONFIG_SPEC.md §8, §8b).
 *
 * The four stored config built-ins (initial capital, commission, pyramiding,
 * short margin) plus the platform-owned symbol list, with the spec's ownership
 * badges (§8b.1), validation messages (§8b.2), live help text (§8b.3) and the
 * sticky resolved-config panel (§8b.4).
 *
 * Controlled by the wizard: the parent owns the values, because they are what
 * its backtest call sends. Ranges *and* defaults come from GET /config-schema —
 * handed up via onSchemaLoaded so the wizard seeds from the same numbers — with
 * the spec's literal ranges as the single fallback (BOT_CONFIG_SCHEMA_FALLBACK).
 *
 * Honesty: only initial capital reaches the DSL backtester today. Pyramiding and
 * short margin are stored and nothing more — the backtester is long-only and
 * counts no same-direction entries — so both say so under the help text and again
 * on their resolved-config rows and in its JSON view.
 */
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Info, Lock, Minus, Plus, Save } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatINRCompact } from "@/lib/formatters";
import {
  getConfigSchema, putStrategyConfig,
  BOT_CONFIG_FIELDS, BOT_CONFIG_SCHEMA_FALLBACK,
  type BotConfig, type BotConfigField, type BotConfigSchema, type ConfigFieldRange,
} from "@/services/strategyBuilder";

// ── Props ───────────────────────────────────────────────────────────
interface Props {
  /** Null until the wizard has created the strategy (first backtest / save). */
  strategyId: string | null;
  value: BotConfig;
  onChange: (next: BotConfig) => void;
  /** Platform-owned symbols, from the universe/screen step. */
  symbols: string[];
  /** Where those symbols came from, e.g. "NIFTY500". */
  universeLabel?: string;
  /** How many fields are invalid: the wizard disables "Run backtest" while it is
   *  non-zero and shows it as the Bot-details tab's error badge (§8, §8b.2). */
  onErrorCountChange?: (count: number) => void;
  /** The fetched schema, so the wizard can seed its form from the same defaults
   *  this panel validates against (one source of truth, never a second copy). */
  onSchemaLoaded?: (schema: BotConfigSchema) => void;
}

// ── Formatting helpers ──────────────────────────────────────────────
const inrFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
/** ₹1,00,000 — Indian grouping, no forced decimals. */
const inr = (rupees: number) => `₹${inrFmt.format(rupees)}`;

/** Accepts what people actually type: "10,00,000", "₹1000000", " 5 ". */
function parseNum(raw: string): number | null {
  const cleaned = raw.replace(/[₹,\s]/g, "");
  if (!cleaned) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

const belowMin = (n: number, r: ConfigFieldRange) => (r.exclusiveMin ? n <= r.min : n < r.min);
const aboveMax = (n: number, r: ConfigFieldRange) => (r.exclusiveMax ? n >= r.max : n > r.max);

// ── Validation (§8b.2 — these messages are the mockup's, verbatim) ──
type Drafts = Record<"initial_capital" | "commission_pct" | "short_margin_pct", string>;
type Errors = Partial<Record<BotConfigField, string>>;

function validate(drafts: Drafts, pyramiding: number, schema: BotConfigSchema): Errors {
  const errors: Errors = {};

  const cap = parseNum(drafts.initial_capital);
  if (cap == null) errors.initial_capital = "Enter an amount in rupees, like 1,00,000.";
  else if (belowMin(cap, schema.initial_capital)) errors.initial_capital = "Initial capital must be above ₹0.";
  else if (aboveMax(cap, schema.initial_capital)) errors.initial_capital = "Maximum is ₹1,000 Cr (10,000,000,000).";

  const com = parseNum(drafts.commission_pct);
  if (com == null) errors.commission_pct = "Enter a percentage from 0 to 5.";
  else if (belowMin(com, schema.commission_pct) || aboveMax(com, schema.commission_pct))
    errors.commission_pct = "Commission must be between 0% and 5%.";

  const sm = parseNum(drafts.short_margin_pct);
  if (sm == null) errors.short_margin_pct = "Enter a percentage above 0, up to 100.";
  else if (belowMin(sm, schema.short_margin_pct) || aboveMax(sm, schema.short_margin_pct))
    errors.short_margin_pct = "Short margin must be above 0% and at most 100%.";

  // The stepper cannot produce an invalid value (§8b.2), but guard anyway.
  if (!Number.isInteger(pyramiding) || pyramiding < schema.pyramiding.min)
    errors.pyramiding = "Pyramiding must be a whole number, 0 or more.";

  return errors;
}

const draftsOf = (c: BotConfig): Drafts => ({
  initial_capital: String(c.initial_capital),
  commission_pct: String(c.commission_pct),
  short_margin_pct: String(c.short_margin_pct),
});

// ── Component ───────────────────────────────────────────────────────
export default function BotDetailsPanel({
  strategyId, value, onChange, symbols, universeLabel, onErrorCountChange, onSchemaLoaded,
}: Props) {
  const [schema, setSchema] = useState<BotConfigSchema>(BOT_CONFIG_SCHEMA_FALLBACK);
  const [schemaFellBack, setSchemaFellBack] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>(() => draftsOf(value));
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Fetch the shared schema once; hand it to the wizard too, so its form seeds from
  // the same defaults this panel validates against. On failure keep the spec ranges
  // and say so — the form still validates, it just isn't reading them from the backend.
  useEffect(() => {
    let alive = true;
    getConfigSchema()
      .then((s) => {
        if (!alive) return;
        setSchema(s); setSchemaFellBack(false); onSchemaLoaded?.(s);
      })
      .catch(() => { if (alive) setSchemaFellBack(true); });
    return () => { alive = false; };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // Re-seed the text drafts when the parent swaps the config in (e.g. the GET
  // after the strategy is created). Edits we emitted ourselves are skipped so
  // typing is never clobbered.
  const emitted = useRef(value);
  useEffect(() => {
    if (value !== emitted.current) { emitted.current = value; setDrafts(draftsOf(value)); }
  }, [value]);

  const errors = validate(drafts, value.pyramiding, schema);
  const errorCount = Object.keys(errors).length;

  useEffect(() => { onErrorCountChange?.(errorCount); }, [errorCount, onErrorCountChange]);

  const emit = (next: BotConfig) => { emitted.current = next; onChange(next); };

  /** Keep the typed text, and push the number up only when it parses. */
  const setNumeric = (field: keyof Drafts, raw: string) => {
    setDrafts((d) => ({ ...d, [field]: raw }));
    setSavedAt(null);
    const n = parseNum(raw);
    if (n != null) emit({ ...value, [field]: n });
  };

  const setPyramiding = (n: number) => {
    setSavedAt(null);
    emit({ ...value, pyramiding: Math.max(schema.pyramiding.min, Math.round(n)) });
  };

  const save = async () => {
    if (!strategyId || errorCount > 0) return;
    setSaving(true); setSaveError(null);
    try {
      await putStrategyConfig(strategyId, {
        initial_capital: value.initial_capital,
        commission_pct: value.commission_pct,
        pyramiding: value.pyramiding,
        short_margin_pct: value.short_margin_pct,
      });
      setSavedAt(new Date().toLocaleTimeString("en-IN"));
    } catch (e) {
      setSaveError((e as { message?: string })?.message || "Couldn't save the config");
    } finally { setSaving(false); }
  };

  const cap = parseNum(drafts.initial_capital);
  const com = parseNum(drafts.commission_pct);
  const sm = parseNum(drafts.short_margin_pct);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-5" data-testid="bot-details-panel">
      {/* ── Fields ──────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4">
        <div>
          <h2 className="text-[15px] font-semibold text-ink">Bot details</h2>
          <p className="text-[12px] text-ink-3 mt-0.5">
            The config the engine starts a run with. Set it before you backtest.
          </p>
        </div>

        {errorCount > 0 && (
          <div className="flex items-center gap-1.5 rounded-lg border border-neg/30 bg-neg/10 px-3 py-2 text-[12px] text-neg"
            data-testid="bot-error-count">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            {errorCount} {errorCount === 1 ? "field needs" : "fields need"} fixing before you can run a backtest.
          </div>
        )}

        {/* Symbols — platform-owned, read-only (the universe IS the source) */}
        <ConfigField label="Symbols" badge="Platform · read-only in code">
          <div className="flex flex-wrap gap-1.5" data-testid="bot-symbols">
            {symbols.length === 0 ? (
              <span className="text-[12.5px] text-ink-3">No symbols resolved yet.</span>
            ) : (
              symbols.slice(0, 40).map((s) => (
                <span key={s}
                  className="inline-flex items-center gap-1 rounded-md border border-hairline bg-surface-2 px-2 py-0.5 font-mono text-[11.5px] text-ink-2">
                  <Lock className="h-3 w-3 text-ink-4" /> {s}
                </span>
              ))
            )}
            {symbols.length > 40 && (
              <span className="text-[11.5px] text-ink-4 self-center">+{symbols.length - 40} more</span>
            )}
          </div>
          <p className="text-[11px] text-ink-3 mt-1.5" data-testid="bot-symbols-note">
            {symbols.length === 0
              ? `Symbols come from the universe step${universeLabel ? ` (${universeLabel})` : ""} — run the Screen step to see which ones it selects.`
              : `Symbols come from the universe step${universeLabel ? ` (${universeLabel})` : ""}; the screen picks them per run. There's nothing to edit here.`}
          </p>
        </ConfigField>

        {/* Initial capital */}
        <ConfigField label="Initial capital (INR)" badge="Overridable in code" error={errors.initial_capital}>
          <input
            type="text" inputMode="decimal" value={drafts.initial_capital}
            onChange={(e) => setNumeric("initial_capital", e.target.value)}
            placeholder="10,00,000" data-testid="bot-capital"
            className={cn(
              "w-full max-w-xs px-3 py-2 text-[13px] tabular-nums rounded-lg border bg-bg text-ink",
              errors.initial_capital ? "border-neg" : "border-hairline",
            )}
          />
          {errors.initial_capital
            ? <FieldError testId="bot-capital-error">{errors.initial_capital}</FieldError>
            : (
              <p className="text-[11px] text-ink-3 mt-1" data-testid="bot-capital-help">
                {formatINRCompact(cap as number)}
                {cap === schema.initial_capital.default && " · default"}
              </p>
            )}
        </ConfigField>

        {/* Commission */}
        <ConfigField label="Commission (%)" badge="Read-only in code" error={errors.commission_pct}>
          <input
            type="text" inputMode="decimal" value={drafts.commission_pct}
            onChange={(e) => setNumeric("commission_pct", e.target.value)}
            placeholder="0.05" data-testid="bot-commission"
            className={cn(
              "w-full max-w-[140px] px-3 py-2 text-[13px] tabular-nums rounded-lg border bg-bg text-ink",
              errors.commission_pct ? "border-neg" : "border-hairline",
            )}
          />
          {errors.commission_pct
            ? <FieldError testId="bot-commission-error">{errors.commission_pct}</FieldError>
            : (
              <p className="text-[11px] text-ink-3 mt-1" data-testid="bot-commission-help">
                {inr((com as number) * 1000)} on every ₹1,00,000 traded, charged on each buy, sell, short and close.
              </p>
            )}
        </ConfigField>

        {/* Pyramiding — integer stepper, floor 0 */}
        <ConfigField label="Pyramiding" badge="Read-only in code" error={errors.pyramiding}>
          <div className="flex items-center gap-2">
            <div className="inline-flex items-center rounded-lg border border-hairline bg-bg">
              <button type="button" onClick={() => setPyramiding(value.pyramiding - 1)}
                disabled={value.pyramiding <= schema.pyramiding.min}
                aria-label="Decrease pyramiding" data-testid="bot-pyramiding-dec"
                className="px-2.5 py-2 text-ink-3 hover:text-ink disabled:opacity-40 disabled:cursor-not-allowed">
                <Minus className="h-3.5 w-3.5" />
              </button>
              <span className="w-10 text-center text-[13px] tabular-nums text-ink" data-testid="bot-pyramiding">
                {value.pyramiding}
              </span>
              <button type="button" onClick={() => setPyramiding(value.pyramiding + 1)}
                aria-label="Increase pyramiding" data-testid="bot-pyramiding-inc"
                className="px-2.5 py-2 text-ink-3 hover:text-ink">
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
            {/* {N+1} allowed · next rejected — filled ticks plus one dashed reject */}
            <div className="flex items-center gap-1.5" data-testid="bot-pyramiding-slots">
              <span className="flex items-center gap-1">
                {Array.from({ length: Math.min(value.pyramiding + 1, 8) }).map((_, i) => (
                  <span key={i} className="h-3.5 w-1.5 rounded-sm bg-accent" />
                ))}
                <span className="h-3.5 w-1.5 rounded-sm border border-dashed border-neg" />
              </span>
              <span className="text-[11px] text-ink-4">{value.pyramiding + 1} allowed · next rejected</span>
            </div>
          </div>
          {errors.pyramiding
            ? <FieldError testId="bot-pyramiding-error">{errors.pyramiding}</FieldError>
            : (
              <p className="text-[11px] text-ink-3 mt-1" data-testid="bot-pyramiding-help">
                {value.pyramiding === 0
                  ? "One entry per direction. The next same-direction signal is rejected with PYRAMIDING_LIMIT."
                  : `Up to ${value.pyramiding + 1} same-direction entries. The next signal is rejected with PYRAMIDING_LIMIT.`}
              </p>
            )}
          {!schema.pyramiding.enforcedByEngine && (
            <NotLiveNote testId="bot-pyramiding-note">
              Stored only for now — the backtester counts no same-direction entries, so this value changes nothing in a run.
            </NotLiveNote>
          )}
        </ConfigField>

        {/* Short margin */}
        <ConfigField label="Short margin (%)" badge="Read-only in code" error={errors.short_margin_pct}>
          <input
            type="text" inputMode="decimal" value={drafts.short_margin_pct}
            onChange={(e) => setNumeric("short_margin_pct", e.target.value)}
            placeholder="100" data-testid="bot-short-margin"
            className={cn(
              "w-full max-w-[140px] px-3 py-2 text-[13px] tabular-nums rounded-lg border bg-bg text-ink",
              errors.short_margin_pct ? "border-neg" : "border-hairline",
            )}
          />
          {errors.short_margin_pct
            ? <FieldError testId="bot-short-margin-error">{errors.short_margin_pct}</FieldError>
            : (
              <p className="text-[11px] text-ink-3 mt-1" data-testid="bot-short-margin-help">
                {inr((sm as number) * 1000)} blocked per ₹1,00,000 short. The position force-closes if losses use up the block.
              </p>
            )}
          {!schema.short_margin_pct.enforcedByEngine && (
            <NotLiveNote testId="bot-short-margin-note">
              Stored only for now — the backtester is long-only, so this value changes nothing in a run.
            </NotLiveNote>
          )}
        </ConfigField>

        {schemaFellBack && (
          <p className="flex items-start gap-1.5 text-[11px] text-warm" data-testid="bot-schema-fallback">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            Couldn't load the shared config schema — validating against the ranges in the spec instead.
          </p>
        )}

        {/* Save */}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button variant="default" size="sm" onClick={save}
            disabled={!strategyId || saving || errorCount > 0} data-testid="bot-save">
            <Save className="h-3.5 w-3.5 mr-1.5" /> {saving ? "Saving…" : "Save config"}
          </Button>
          {!strategyId ? (
            <span className="text-[11.5px] text-ink-3" data-testid="bot-save-note">
              No strategy yet — these values are held here and saved with the strategy when you run the first backtest.
            </span>
          ) : savedAt ? (
            <span className="inline-flex items-center gap-1 text-[11.5px] text-pos" data-testid="bot-save-status">
              <Check className="h-3.5 w-3.5" /> Saved at {savedAt}
            </span>
          ) : null}
          {saveError && (
            <span className="text-[11.5px] text-neg" data-testid="bot-save-error">{saveError}</span>
          )}
        </div>
      </div>

      {/* ── Resolved config (§8b.4) ─────────────────────────────── */}
      {/* The schema's own admission of which keys a run ignores travels with the
          values, so the panel can't imply a stored-only field reaches the engine. */}
      <ResolvedConfig
        config={{ ...value, symbols }}
        notEnforced={BOT_CONFIG_FIELDS.filter((f) => !schema[f].enforcedByEngine)}
      />
    </div>
  );
}

// ── Field shell ─────────────────────────────────────────────────────
function ConfigField({ label, badge, error, children }: {
  label: string; badge: string; error?: string; children: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-xl border bg-surface-1 p-3.5", error ? "border-neg/40" : "border-hairline")}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <span className="text-[12.5px] font-medium text-ink">{label}</span>
        <Badge tone="outline" className="shrink-0 whitespace-nowrap">{badge}</Badge>
      </div>
      {children}
    </div>
  );
}

function FieldError({ testId, children }: { testId: string; children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-1.5 text-[11px] text-neg mt-1" data-testid={testId}>
      <AlertTriangle className="h-3.5 w-3.5 mt-px shrink-0" /> {children}
    </p>
  );
}

/** The one place the UI admits a field is stored but not yet acted on. */
function NotLiveNote({ testId, children }: { testId: string; children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-1.5 text-[11px] text-warm mt-1.5" data-testid={testId}>
      <Info className="h-3.5 w-3.5 mt-px shrink-0" /> {children}
    </p>
  );
}

// ── Resolved config panel ───────────────────────────────────────────
/** Where each value came from. "Code" is the design's pill for anything a Python
 *  strategy_info set — i.e. custom keys. The DSL wizard has no code step, so no
 *  built-in resolves to Code here; a stored custom key still shows it. */
type Source = "Platform" | "Bot details" | "Code";

const SOURCES: Record<string, Source> = {
  symbols: "Platform",
  initial_capital: "Bot details",
  commission_pct: "Bot details",
  pyramiding: "Bot details",
  short_margin_pct: "Bot details",
};

function ResolvedConfig({ config, notEnforced }: {
  config: BotConfig;
  /** Keys the engine stores but never acts on, straight from the schema. */
  notEnforced: BotConfigField[];
}) {
  const [view, setView] = useState<"fields" | "json">("fields");
  const inert = new Set<string>(notEnforced);

  const json = {
    schema_version: config.schema_version ?? 1,
    symbols: config.symbols,
    initial_capital: config.initial_capital,
    commission_pct: config.commission_pct,
    pyramiding: config.pyramiding,
    short_margin_pct: config.short_margin_pct,
    custom: config.custom ?? {},
    // Same key the API returns: the JSON view must not read as "all of this is live".
    not_enforced_by_engine: notEnforced,
  };

  const rows: { key: string; value: string; note?: string }[] = [
    {
      key: "symbols",
      value: config.symbols.length === 0 ? "—" : `${config.symbols.length} symbol${config.symbols.length === 1 ? "" : "s"}`,
      note: config.symbols.slice(0, 6).join(", ") || undefined,
    },
    { key: "initial_capital", value: inr(config.initial_capital) },
    { key: "commission_pct", value: `${config.commission_pct}%` },
    { key: "pyramiding", value: String(config.pyramiding) },
    { key: "short_margin_pct", value: `${config.short_margin_pct}%` },
  ];
  for (const [k, v] of Object.entries(config.custom ?? {})) {
    rows.push({ key: k, value: JSON.stringify(v), note: "custom key" });
  }

  return (
    <aside className="lg:sticky lg:top-4 self-start w-full rounded-xl border border-hairline bg-surface-1 overflow-hidden"
      data-testid="resolved-config">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-hairline">
        <span className="text-[11px] uppercase tracking-wide text-ink-4">Resolved config</span>
        <div className="flex items-center gap-0.5 rounded-md bg-surface-2 p-0.5 text-[11px]">
          {(["fields", "json"] as const).map((v) => (
            <button key={v} type="button" onClick={() => setView(v)}
              data-testid={`resolved-toggle-${v}`}
              className={cn("rounded px-2 py-0.5 capitalize",
                view === v ? "bg-accent/15 text-accent font-medium" : "text-ink-3 hover:text-ink")}>
              {v === "json" ? "JSON" : "Fields"}
            </button>
          ))}
        </div>
      </div>

      {view === "fields" ? (
        <ul>
          {rows.map((r) => (
            <li key={r.key} className="px-3 py-2 border-t border-hairline first:border-t-0"
              data-testid={`resolved-row-${r.key}`}>
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-[11.5px] text-ink-3 truncate">{r.key}</span>
                <SourcePill source={SOURCES[r.key] ?? "Code"} fieldKey={r.key} />
              </div>
              <div className="text-[12.5px] text-ink tabular-nums mt-0.5">{r.value}</div>
              {r.note && <div className="text-[10.5px] text-ink-4 mt-0.5 truncate">{r.note}</div>}
              {inert.has(r.key) && (
                <div className="flex items-start gap-1 text-[10.5px] text-warm mt-0.5"
                  data-testid={`resolved-not-live-${r.key}`}>
                  <Info className="h-3 w-3 mt-px shrink-0" /> Stored only — a run doesn't apply it.
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <pre className="px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-2 overflow-x-auto"
          data-testid="resolved-json">{JSON.stringify(json, null, 2)}</pre>
      )}

      <div className="px-3 py-2 border-t border-hairline text-[10.5px] text-ink-4"
        data-testid="resolved-footer">
        {notEnforced.length === 0
          ? "The values the next backtest run starts from."
          : "The values the next backtest run starts from — except the keys marked stored only, which a run ignores."}
      </div>
    </aside>
  );
}

function SourcePill({ source, fieldKey }: { source: Source; fieldKey: string }) {
  const cls = source === "Platform" ? "text-ink-3 border-hairline-2"
    : source === "Bot details" ? "text-accent border-accent/40"
    : "text-warm border-warm/40";
  return (
    <span data-testid={`resolved-source-${fieldKey}`}
      className={cn("shrink-0 rounded-full border px-1.5 py-px text-[9.5px] font-medium whitespace-nowrap", cls)}>
      {source}
    </span>
  );
}
