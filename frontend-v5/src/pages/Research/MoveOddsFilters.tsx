/**
 * Move odds · filters (owner's design of 2026-09-18): market-cap buckets, a Screener-style ratio picker with
 * conditions, and event categories. Ratios the universe does not have are listed but cannot be picked, with the reason;
 * a condition applies only once a number is typed, and stocks without that value are excluded (the count says how many).
 */
import { useMemo, useState } from "react";
import type { MoveProfile } from "@/services/adapters/moveOdds.adapter";
import { CAPS, SUGGEST, condActive, type Cap, type Cond } from "./moveOddsProfile";

const COLUMNS = ["recent", "preceding", "historical"] as const;

export function FilterBar(props: {
  profile: MoveProfile | null;
  unavailable: string | null;                    // why the profile controls are off (load failure), or null
  cap: Cap; setCap: (c: Cap) => void;
  capCounts: Partial<Record<Cap, number>>;
  picked: string[]; conds: Record<string, Cond>;
  setCond: (key: string, c: Cond) => void; removePicked: (key: string) => void;
  panelOpen: boolean; setPanelOpen: (b: boolean) => void;
  evtOpen: boolean; setEvtOpen: (b: boolean) => void; evtCat: string;
  clearAll: () => void; canClear: boolean;
}) {
  const { profile, unavailable } = props;
  const off = !profile;
  const defs = useMemo(() => Object.fromEntries((profile?.catalogue ?? []).map((d) => [d.key, d])), [profile]);
  const active = Object.values(props.conds).filter(condActive).length;
  const evtLabel = props.evtCat === "All" ? "All" : profile?.event_categories.find((e) => e.key === props.evtCat)?.label ?? props.evtCat;
  return (
    <div className="mo-fbar" data-testid="mo-filterbar">
      <div className="mo-seg" role="group" aria-label="Market cap">
        {CAPS.map((c) => (
          <button key={c} type="button" aria-pressed={props.cap === c} disabled={off} data-testid={`mo-cap-${c}`} onClick={() => props.setCap(c)}>
            {c === "All" ? "All caps" : `${c} cap`}
            {c !== "All" && props.capCounts[c] != null && <span className="mo-seg-n">{props.capCounts[c]}</span>}
          </button>
        ))}
      </div>
      <span className="mo-fbar-sep" aria-hidden="true" />
      <button type="button" className="mo-fbtn" aria-expanded={props.panelOpen} aria-controls="mo-ratio-panel" disabled={off}
              data-active={active > 0 || props.panelOpen} data-testid="mo-ratio-toggle" onClick={() => props.setPanelOpen(!props.panelOpen)}>
        Filter ratios{active ? ` · ${active} on` : props.picked.length ? ` · ${props.picked.length}` : ""}<span aria-hidden="true">{props.panelOpen ? " ▴" : " ▾"}</span>
      </button>
      <button type="button" className="mo-fbtn" aria-expanded={props.evtOpen} aria-controls="mo-evt-bar" disabled={off}
              data-active={props.evtOpen || props.evtCat !== "All"} data-testid="mo-evt-toggle" onClick={() => props.setEvtOpen(!props.evtOpen)}>
        Events · {evtLabel}<span aria-hidden="true">{props.evtOpen ? " ▴" : " ▾"}</span>
      </button>
      <ul className="mo-conds" aria-label="Ratio conditions">
        {props.picked.map((k) => {
          const d = defs[k];
          if (!d) return null;
          const c = props.conds[k] ?? { op: SUGGEST[k]?.[0] ?? ">", val: "" };
          const on = condActive(c);
          return (
            <li key={k} className="mo-cond" data-on={on} data-testid={`mo-cond-${k}`}>
              <span className="mo-cond-label">{d.label}</span>
              <button type="button" className="mo-cond-op" data-testid={`mo-cond-op-${k}`}
                      aria-label={`${d.label}: ${c.op === ">" ? "greater than" : "less than"}; switch`}
                      onClick={() => props.setCond(k, { ...c, op: c.op === ">" ? "<" : ">" })}>{c.op}</button>
              <input className="mo-cond-val" inputMode="decimal" value={c.val} data-testid={`mo-cond-val-${k}`}
                     placeholder={SUGGEST[k] ? String(SUGGEST[k][1]) : "value"} aria-label={`${d.label} threshold`}
                     onChange={(e) => props.setCond(k, { ...c, val: e.target.value })} />
              <span className="mo-cond-unit" aria-hidden="true">{UNIT[d.unit]}</span>
              <button type="button" className="mo-cond-x" aria-label={`Remove ${d.label}`} data-testid={`mo-cond-x-${k}`} onClick={() => props.removePicked(k)}>×</button>
            </li>
          );
        })}
      </ul>
      <button type="button" className="mo-clear" disabled={!props.canClear} data-testid="mo-clear" onClick={props.clearAll}>Clear</button>
      {unavailable && <p className="mo-mini mo-fbar-off" role="status" data-testid="mo-profile-off">{unavailable}</p>}
    </div>
  );
}

const UNIT: Record<string, string> = { cr: "₹ Cr", pct: "%", x: "×", rs: "₹", pts: "pts" };

export function RatioPanel({ profile, picked, toggle, close }: {
  profile: MoveProfile; picked: string[]; toggle: (key: string) => void; close: () => void;
}) {
  const [group, setGroup] = useState(profile.groups[0] ?? "Most Used");
  const [query, setQuery] = useState("");
  const term = query.trim().toLowerCase();
  const list = profile.catalogue.filter((d) => (term ? d.label.toLowerCase().includes(term) : d.group === group));
  const live = profile.catalogue.filter((d) => d.available).length;
  return (
    <section id="mo-ratio-panel" className="mo-rpanel" aria-label="Filter ratios" data-testid="mo-ratio-panel">
      <div className="mo-rpanel-top">
        <label className="sr-only" htmlFor="mo-rq">Find a ratio</label>
        <input id="mo-rq" type="search" placeholder="eg. return on capital" value={query} data-testid="mo-ratio-search" onChange={(e) => setQuery(e.target.value)} />
        <div className="mo-rgroups" role="group" aria-label="Ratio group">
          {profile.groups.map((g) => (
            <button key={g} type="button" aria-pressed={!term && group === g} data-testid={`mo-rgroup-${g.replace(/[^A-Za-z]/g, "")}`}
                    onClick={() => { setGroup(g); setQuery(""); }}>{g}</button>
          ))}
        </div>
      </div>
      <div className="mo-rcols">
        {COLUMNS.map((col) => {
          const items = list.filter((d) => d.column === col);
          return (
            <div key={col} className="mo-rcol">
              <h4>{col}</h4>
              {items.length === 0 && (
                <p className="mo-mini">{group === "User Ratios" && !term ? "Custom ratios are not available yet." : "None in this group."}</p>
              )}
              {items.map((d) => {
                const id = `mo-r-${d.key}`;
                return (
                  <div key={d.key} className="mo-ritem" data-available={d.available} data-testid={`mo-ratio-${d.key}`}>
                    <input id={id} type="checkbox" checked={picked.includes(d.key)} disabled={!d.available} onChange={() => toggle(d.key)}
                           aria-describedby={`${id}-why`} />
                    <label htmlFor={id} title={d.available ? (d.note ?? undefined) : (d.reason ?? undefined)}>{d.label}</label>
                    <span id={`${id}-why`} className="mo-rwhy">
                      {d.available ? <><span className="mo-rdot live" aria-hidden="true" /><span className="sr-only">has data for {d.n} stocks</span></>
                        : <><span className="mo-rdot" aria-hidden="true" /><span className="mo-rreason">{d.reason}</span></>}
                    </span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
      <div className="mo-rpanel-foot">
        <span className="mo-mini"><span className="mo-rdot live" aria-hidden="true" /> has data ({live} of {profile.catalogue.length}) · <span className="mo-rdot" aria-hidden="true" /> not available, with the reason.
          Values as of {profile.features_as_of ?? "—"}; a 0 in dividend yield or pledge can mean none or no data.</span>
        <button type="button" className="mo-btn" onClick={close} data-testid="mo-ratio-done">Done</button>
      </div>
    </section>
  );
}

export function EventBar({ profile, evtCat, setEvtCat, evtSort, setEvtSort, counts }: {
  profile: MoveProfile; evtCat: string; setEvtCat: (k: string) => void;
  evtSort: "material" | "latest"; setEvtSort: (s: "material" | "latest") => void; counts: Record<string, number>;
}) {
  const withAny = counts.__any ?? 0;
  const head = evtCat === "All" ? `All filings · ${withAny} stocks on record`
    : `${profile.event_categories.find((e) => e.key === evtCat)?.label ?? evtCat} · ${counts[evtCat] ?? 0} stocks on record`;
  return (
    <div id="mo-evt-bar" className="mo-evbar" data-testid="mo-evt-bar">
      <span className="mo-evbar-head" data-testid="mo-evt-head">{head}</span>
      <div className="mo-evpills" role="group" aria-label="Event category">
        <button type="button" aria-pressed={evtCat === "All"} data-testid="mo-evt-All" onClick={() => setEvtCat("All")}>All</button>
        {profile.event_categories.filter((e) => e.key !== "other").map((e) => (
          <button key={e.key} type="button" aria-pressed={evtCat === e.key} data-testid={`mo-evt-${e.key}`} onClick={() => setEvtCat(e.key)}>
            {e.label}<span className="mo-seg-n">{counts[e.key] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="mo-evsort" role="group" aria-label="Order stocks with this category by">
        <span className="mo-mini">Sort</span>
        <button type="button" aria-pressed={evtSort === "material"} data-testid="mo-evt-sort-material" onClick={() => setEvtSort("material")}
                title="Events classified positive, negative or mixed">Material</button>
        <button type="button" aria-pressed={evtSort === "latest"} data-testid="mo-evt-sort-latest" onClick={() => setEvtSort("latest")}>Latest</button>
      </div>
    </div>
  );
}
