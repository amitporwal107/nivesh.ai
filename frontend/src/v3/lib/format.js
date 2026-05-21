// Indian-locale formatters used by V3 screens.

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const INR_PRECISE = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

export function inr(value, { precise = false, sign = false } = {}) {
  if (value == null || Number.isNaN(value)) return "—";
  const fmt = precise ? INR_PRECISE : INR;
  const out = fmt.format(Math.abs(value));
  const prefix = sign && value > 0 ? "+" : value < 0 ? "−" : "";
  return `${prefix}₹${out}`;
}

export function inrCompact(value) {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `₹${(value / 1e7).toFixed(value / 1e7 >= 100 ? 0 : 2)} Cr`;
  if (abs >= 1e5) return `₹${(value / 1e5).toFixed(value / 1e5 >= 100 ? 0 : 2)} L`;
  if (abs >= 1e3) return `₹${(value / 1e3).toFixed(value / 1e3 >= 100 ? 0 : 1)}k`;
  return `₹${INR.format(value)}`;
}

export function pct(value, digits = 1) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function count(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return INR.format(value);
}

export function dateLabel(d = new Date()) {
  return d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" });
}
