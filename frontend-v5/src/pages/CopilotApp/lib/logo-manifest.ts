/**
 * Logo files for the icons in components/EntityIcon.tsx.
 *
 * The repo ships no company, fund-house or broker logo files, and no API the
 * app calls returns a logo URL, so every map below is empty and every icon is
 * drawn as a monogram tile. To show a real logo, put the file under
 * frontend-v5/public/logos/<kind>/ and register it here by key:
 *
 *   stock      the NSE symbol in upper case           "RELIANCE": "logos/stock/RELIANCE.svg"
 *   fundHouse  the fund house name from fundHouseOf   "HDFC": "logos/fund-house/hdfc.svg"
 *   broker     the broker name in lower case          "zerodha": "logos/broker/zerodha.svg"
 *
 * Paths are relative to the app's base URL. Only registered keys are ever
 * requested, so an unregistered name costs no network call.
 */
export type LogoKind = "stock" | "fundHouse" | "broker";

export const LOGOS: Record<LogoKind, Record<string, string>> = {
  stock: {},
  fundHouse: {},
  broker: {},
};

/** Absolute URL of a registered logo, or null when none is registered. */
export function logoUrl(kind: LogoKind, key: string): string | null {
  const path = LOGOS[kind][key];
  if (!path) return null;
  return `${import.meta.env.BASE_URL}${path.replace(/^\/+/, "")}`;
}
