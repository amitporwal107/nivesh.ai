/**
 * The Screener page's metric catalog: the chat's primitives plus the mutual-fund metrics that only
 * POST /api/screeners/run can screen on (backend/routes/screeners.py _MF_METRICS).
 *
 * The fund metrics are NOT added to components/chat/screenerPrimitives.ts: that catalog also feeds the
 * chat composer and the chat sentence parser, which would silently drop a phrase it does not know and
 * return a broader screen than was asked for. A screen with a fund rule therefore has no chat sentence.
 */
import {
  PRIMITIVE_BY_KEY, PRIMITIVE_GROUPS, compileScreenQuery, type BuilderCondition, type ScreenPrimitive,
} from "@/components/chat/screenerPrimitives";

export const FUND_PRIMITIVES: ScreenPrimitive[] = [
  { key: "mfChange",    label: "MF holding change",   cat: "Mutual funds", hint: "disclosed shares, 3M", tag: "%",      qlabel: "MF holding change",   op: "over" },
  { key: "amcsUp",      label: "Fund houses raising", cat: "Mutual funds", hint: "net of their schemes", tag: "houses", qlabel: "fund houses raising", op: "over" },
  { key: "amcsDn",      label: "Fund houses cutting", cat: "Mutual funds", hint: "net of their schemes", tag: "houses", qlabel: "fund houses cutting", op: "under" },
  { key: "amcsHolding", label: "Fund houses holding", cat: "Mutual funds", hint: "any scheme",           tag: "houses", qlabel: "fund houses holding", op: "over" },
];

export const FUND_KEYS = new Set(FUND_PRIMITIVES.map((p) => p.key));

export const PAGE_BY_KEY: Record<string, ScreenPrimitive> = {
  ...PRIMITIVE_BY_KEY,
  ...Object.fromEntries(FUND_PRIMITIVES.map((p) => [p.key, p])),
};

export const PAGE_GROUPS: { cat: string; items: ScreenPrimitive[] }[] = [
  ...PRIMITIVE_GROUPS,
  { cat: "Mutual funds", items: FUND_PRIMITIVES },
];

type Rule = Pick<BuilderCondition, "key" | "op" | "value">;

/** True when any rule with a value is a fund rule, so the chat's parser could not read this screen. */
export const hasFundRule = (rules: Rule[]): boolean => rules.some((r) => FUND_KEYS.has(r.key) && r.value.trim() !== "");

/** The screen in words for this page. Same shape as the chat sentence, with the fund rules in it. */
export function screenInWords(rules: Rule[], bucket?: string): string {
  const base = compileScreenQuery(rules.filter((r) => !FUND_KEYS.has(r.key)).map((r, i) => ({ id: i, ...r })), bucket);
  const fund = rules
    .filter((r) => FUND_KEYS.has(r.key) && r.value.trim() !== "")
    .map((r) => `${PAGE_BY_KEY[r.key].qlabel} ${r.op} ${r.value.trim()}`);
  if (!fund.length) return base;
  if (!base) return `Screen stocks where ${fund.join(", ")}`;
  // base is "Screen [bucket] stocks where a, b" or "Screen [bucket] stocks"
  return base.includes(" where ") ? `${base}, ${fund.join(", ")}` : `${base} where ${fund.join(", ")}`;
}

/** The sentence the Copilot can run: null when a fund rule would be lost in it. */
export function chatSentence(rules: Rule[], bucket?: string): string | null {
  if (hasFundRule(rules)) return null;
  return compileScreenQuery(rules.map((r, i) => ({ id: i, ...r })), bucket) || null;
}
