/**
 * The icon that sits beside a name: a company (stock), a fund house, a broker.
 *
 * A real logo is drawn only when one is registered in lib/logo-manifest.ts.
 * None is today, so each icon is a monogram tile — the name's short code on a
 * tint that is always the same for that name — and the tile stays as the
 * fallback if a registered image fails to load.
 *
 *   <StockName symbol="RELIANCE" name="Reliance Industries" />
 *   <FundName name="HDFC Flexi Cap Fund - Direct Growth" sub="Flexi cap" />
 *   <BrokerName name="Zerodha" sub="Last synced today" />
 *
 * Use the *Name components wherever a row names a stock, a fund or a broker;
 * use the bare *Icon components where the name is laid out separately.
 */
import { useState, type ReactNode } from "react";
import { logoUrl, type LogoKind } from "../lib/logo-manifest";

/** Hues for the tiles. One is picked per name, so a name keeps its colour. */
const HUES = [158, 38, 232, 268, 196, 12, 320, 84];

function hueOf(key: string): number {
  let h = 5381;
  for (let i = 0; i < key.length; i += 1) h = ((h << 5) + h + key.charCodeAt(i)) >>> 0;
  return HUES[h % HUES.length];
}

/** Two characters for a tile: initials of a two-word name, else its first two letters. */
export function monogramOf(name: string): string {
  const words = name.replace(/[^A-Za-z0-9 &]/g, " ").split(/\s+/).filter((w) => w && w !== "&");
  if (words.length === 0) return "·";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/**
 * Fund houses as they start a scheme name, longest first so "ICICI Prudential"
 * wins over a one-word match. The value is the name shown and used as the key.
 */
const FUND_HOUSES: Array<[prefix: string, house: string]> = [
  ["aditya birla sun life", "Aditya Birla Sun Life"],
  ["baroda bnp paribas", "Baroda BNP Paribas"],
  ["mahindra manulife", "Mahindra Manulife"],
  ["franklin templeton", "Franklin Templeton"],
  ["icici prudential", "ICICI Prudential"],
  ["whiteoak capital", "WhiteOak Capital"],
  ["bajaj finserv", "Bajaj Finserv"],
  ["franklin india", "Franklin Templeton"],
  ["bank of india", "Bank of India"],
  ["canara robeco", "Canara Robeco"],
  ["motilal oswal", "Motilal Oswal"],
  ["jio blackrock", "Jio BlackRock"],
  ["jm financial", "JM Financial"],
  ["nippon india", "Nippon India"],
  ["parag parikh", "Parag Parikh"],
  ["mirae asset", "Mirae Asset"],
  ["old bridge", "Old Bridge"],
  ["pgim india", "PGIM India"],
  ["angel one", "Angel One"],
  ["edelweiss", "Edelweiss"],
  ["sundaram", "Sundaram"],
  ["360 one", "360 ONE"],
  ["bandhan", "Bandhan"],
  ["invesco", "Invesco"],
  ["quantum", "Quantum"],
  ["shriram", "Shriram"],
  ["zerodha", "Zerodha"],
  ["helios", "Helios"],
  ["taurus", "Taurus"],
  ["groww", "Groww"],
  ["kotak", "Kotak"],
  ["quant", "Quant"],
  ["samco", "Samco"],
  ["trust", "Trust"],
  ["union", "Union"],
  ["unifi", "Unifi"],
  ["ppfas", "Parag Parikh"],
  ["axis", "Axis"],
  ["hdfc", "HDFC"],
  ["hsbc", "HSBC"],
  ["navi", "Navi"],
  ["tata", "Tata"],
  ["dsp", "DSP"],
  ["iti", "ITI"],
  ["lic", "LIC"],
  ["sbi", "SBI"],
  ["uti", "UTI"],
  ["nj", "NJ"],
];

/** The fund house of a scheme ("HDFC Flexi Cap Fund - Direct Growth" → "HDFC"). */
export function fundHouseOf(schemeOrHouse: string): string {
  const s = schemeOrHouse.trim().toLowerCase();
  for (const [prefix, house] of FUND_HOUSES) {
    if (s === prefix || s.startsWith(`${prefix} `)) return house;
  }
  // Not a house this list knows: the first word is the best short name there is.
  return schemeOrHouse.trim().split(/\s+/)[0] ?? "";
}

interface IconProps {
  kind: LogoKind;
  /** Manifest key and the seed for the tile's colour. */
  entityKey: string;
  /** Characters on the tile. */
  letters: string;
  /** Full name, read out for an image logo. */
  label: string;
  size: number;
}

const KIND_ATTR: Record<LogoKind, string> = { stock: "stock", fundHouse: "fund-house", broker: "broker" };

function EntityIcon({ kind, entityKey, letters, label, size }: IconProps) {
  const [failed, setFailed] = useState(false);
  const url = logoUrl(kind, entityKey);
  const radius = size > 32 ? 10 : size > 22 ? 8 : 6;
  const base = { flex: "none", width: size, height: size, borderRadius: radius } as const;

  if (url && !failed) {
    return (
      <img
        data-testid="entity-icon"
        data-kind={KIND_ATTR[kind]}
        data-key={entityKey}
        data-logo="image"
        src={url}
        alt={label}
        width={size}
        height={size}
        loading="lazy"
        onError={() => setFailed(true)}
        style={{ ...base, objectFit: "contain", background: "var(--bg-3)" }}
      />
    );
  }

  const hue = hueOf(`${kind}:${entityKey}`);
  return (
    <span
      aria-hidden
      data-testid="entity-icon"
      data-kind={KIND_ATTR[kind]}
      data-key={entityKey}
      data-logo="monogram"
      className="grid place-items-center"
      style={{
        ...base,
        background: `hsl(${hue} 45% 50% / 0.16)`,
        border: `1px solid hsl(${hue} 45% 50% / 0.32)`,
        color: "var(--cp-ink)",
        fontFamily: "var(--mono)",
        fontSize: size > 32 ? 12 : size > 22 ? 10 : 9,
        letterSpacing: "0.02em",
        lineHeight: 1,
      }}
    >
      {letters}
    </span>
  );
}

/** A listed company, keyed by its exchange symbol. */
export function StockIcon({ symbol, name, size = 28 }: { symbol: string; name?: string | null; size?: number }) {
  const key = symbol.trim().toUpperCase();
  return <EntityIcon kind="stock" entityKey={key} letters={key.replace(/[^A-Z0-9]/g, "").slice(0, 2) || "·"} label={name || key} size={size} />;
}

/** A fund house. Accepts the house's name or any of its scheme names. */
export function FundHouseIcon({ name, size = 28 }: { name: string; size?: number }) {
  const house = fundHouseOf(name);
  return <EntityIcon kind="fundHouse" entityKey={house} letters={monogramOf(house)} label={house} size={size} />;
}

/** A broker or depository account provider. */
export function BrokerIcon({ name, size = 28 }: { name: string; size?: number }) {
  const key = name.trim().toLowerCase();
  return <EntityIcon kind="broker" entityKey={key} letters={monogramOf(name)} label={name} size={size} />;
}

/** An icon with a name beside it and an optional quieter second line. */
export function NameCell({ icon, name, sub, testId }: { icon: ReactNode; name: ReactNode; sub?: ReactNode; testId?: string }) {
  return (
    <span data-testid={testId} className="flex items-center" style={{ gap: 10, minWidth: 0 }}>
      {icon}
      <span className="flex flex-col" style={{ gap: 1, minWidth: 0 }}>
        <span style={{ color: "var(--cp-ink)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
        {sub != null && sub !== "" && (
          <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>
        )}
      </span>
    </span>
  );
}

/** A stock: its icon, then the company name (or the symbol when no name is known). */
export function StockName({ symbol, name, sub, size, testId }: { symbol: string; name?: string | null; sub?: ReactNode; size?: number; testId?: string }) {
  const shown = name && name.trim() ? name : symbol;
  // With a company name on the first line, the symbol moves to the second.
  const second = sub ?? (shown !== symbol ? symbol : undefined);
  return <NameCell testId={testId} icon={<StockIcon symbol={symbol} name={name} size={size} />} name={shown} sub={second} />;
}

/** A mutual fund scheme: its fund house's icon, then the scheme name. */
export function FundName({ name, sub, size, testId }: { name: string; sub?: ReactNode; size?: number; testId?: string }) {
  return <NameCell testId={testId} icon={<FundHouseIcon name={name} size={size} />} name={name} sub={sub} />;
}

/** A broker: its icon, then its name. */
export function BrokerName({ name, sub, size, testId }: { name: string; sub?: ReactNode; size?: number; testId?: string }) {
  return <NameCell testId={testId} icon={<BrokerIcon name={name} size={size} />} name={name} sub={sub} />;
}
