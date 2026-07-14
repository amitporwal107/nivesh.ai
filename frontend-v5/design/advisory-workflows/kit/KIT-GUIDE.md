# Nivesh V5 Screen-Mockup Kit — Authoring Guide

You are designing **high-fidelity screen mockups** for the Nivesh advisory platform in its real
V5 visual language. All styling comes from a shared stylesheet (`v5-kit.css`) that is injected
once into the final page. **You only write HTML that composes the kit's classes.** Do not write
any `<style>`, `<script>`, `<link>`, `<img>`, or external URLs — the page has a strict CSP and a
single shared stylesheet. Inline SVG is allowed (and encouraged) for charts/sparklines.

## The look (do not restate it in CSS — just use the classes)
Warm-cream ground `#F6F4ED`, mint accent `#0E8A55`, **Instrument Serif** for big display numbers &
page titles (`.serif`), **Inter Tight** body, **JetBrains Mono** for micro-labels (`.mono`, already
baked into `.nv-pill`, `.tbl th`, `.stat .k`, `.field label`). Cards are `.nv-card` (14px radius,
hairline border, soft shadow). Everything works in light & dark automatically via tokens — never
hardcode a hex; use the classes.

## Every screen is wrapped like this
```html
<article class="screen" id="wf04-portfolio">
  <div class="cap">
    <span class="nv-pill mint">Live</span>          <!-- mint=Live · amber=Extend · indigo=New -->
    <h3>Live Portfolio Dashboard</h3>
    <span class="route">/v5/portfolio</span>
    <span class="nv-pill">⛓ vendor</span>           <!-- only if vendor-gated; else omit -->
    <p class="desc">One-line purpose + which FRs (FR-04-01/02).</p>
  </div>
  <div class="frame"> … the mockup … </div>
</article>
```

## The device frame (desktop) — the standard container
```html
<div class="frame">
  <div class="chrome"><i></i><i></i><i></i>
    <span class="url">staging.niveshcopilot.com/v5/portfolio</span>
    <span class="nv-pill mint st">Live</span>
  </div>
  <div class="app">
    <!-- collapsed 56px icon rail: keep it on EVERY desktop screen for authenticity.
         Put the logo, 4–6 lucide-ish glyphs (use emoji/unicode), mark the active one .on, avatar at bottom. -->
    <div class="rail">
      <span class="nv-mark" style="width:30px;height:30px;font-size:18px">न</span>
      <span class="ico">◫</span><span class="ico on">◧</span><span class="ico">◎</span><span class="ico">⚑</span><span class="ico">₹</span>
      <span class="sp"></span><span class="av">AP</span>
    </div>
    <div class="view">
      <div class="viewbar">
        <div><div class="vt">Portfolio</div></div>
        <div class="grow"></div>
        <span class="chip neutral">Updated 10:14 PM</span>
        <button class="nv-btn sm">Export</button>
      </div>
      <div class="viewbody"> … real content: stats, tables, charts … </div>
    </div>
  </div>
</div>
```
For a **mobile** screen use `.phone` instead of `.frame` (see kit). Use mobile only where the PRD
implies an investor-facing app screen; MFD/advisor screens are desktop.

## Class cheat-sheet (compose these; full list in v5-kit.css)
- **Layout:** `.viewbody` `.row` `.grid2/3/4` `.col` `.between` `.ch`(card header w/ `.lbl`) `.pad`/`.pad-sm`
- **Cards:** `.nv-card` `.nv-card-2` — always add `.pad` or `.pad-sm` for inner spacing
- **Stat tile:** `.stat`>`.k`(label)+`.v`(number, add `.serif` for hero numbers)+`.d`(delta, add `.pos`/`.neg`)
- **Table:** `.tbl-wrap`>`table.tbl`>`thead th` + `tbody td`; right-align numbers with `.r`, names `.nm`, sub-text `.sub`
- **Status:** `.chip` + `.ok/.warn/.bad/.info/.neutral`; design/status pills `.nv-pill` + `.mint/.amber/.indigo/.danger`; `.tag`
- **Forms:** `.field`>`label`+`.input` (`.input.otp`, `.input.ph` for placeholder), `.seg`(`.on`), `.check`(`.bx.on`), `.switch`(`.off`), `.slider`(`.fill`+`.knob`)
- **Tabs:** `.tabbar`>`.tab`(`.on`)
- **Banners:** `.banner` + `.warn/.info/.bad/.ok`, with a `.bi` icon span + text (bold via `<b>`)
- **Progress:** `.bar`>`i` (width % inline; `.amber`/`.neg`); `.ring` (set `--p:` and `--sz:`, inner `.hole`)
- **Charts:** `.donut` (conic — set `--a/--b/--cc` stops & `--c1..c4` colors) + `.legend`; `.bars`>`i` (heights inline, `.q` = muted); or inline `<svg class="spark">` area+line
- **Kanban/pipeline:** `.kb` (set `--n:`)>`.colk`>`.kh`+`.kcard`
- **List rows:** `.lrow` with `.av`; **empty/loading:** `.empty`, `.skel` (give width/height inline)
- **Money:** always `.num` on figures; Indian format ₹ + lakh/crore (e.g. `₹ 48.2 L`, `₹ 1.24 Cr`), masked PAN `ABCDE1234F → XXXXX1234F`

## Content rules
- **Real, plausible Indian data.** Real AMC/fund names (HDFC Flexi Cap, Parag Parikh Flexi Cap,
  ICICI Pru Bluechip, SBI Small Cap, UTI Nifty 50 Index, Kotak Equity Arbitrage…), realistic NAVs,
  XIRR 9–16%, SIP ₹5k–₹50k, PAN masked, folio numbers, ARN-115287. Never lorem.
- **Show ≥1 non-default state per screen** where meaningful: an alert/breach row, a warning banner,
  an empty state, a loading skeleton, or a validation error — whatever the screen's job implies.
- **Copy from the user's side:** buttons say what they do ("Place order", "Start SIP", "Send eSign link").
- **Density like a real dashboard:** summary first, then detail. Tables get 4–7 rows, not 1.
- Keep each screen's frame **self-contained and not too tall** — one screenful (~440–620px of content).

---

## WORKED EXAMPLE A — desktop dashboard (copy this pattern)
```html
<article class="screen" id="ex-portfolio">
  <div class="cap">
    <span class="nv-pill mint">Live</span><h3>Live Portfolio Dashboard</h3>
    <span class="route">/v5/portfolio</span>
    <p class="desc">Consolidated holdings with XIRR, allocation and day-change. FR-04-01/02.</p>
  </div>
  <div class="frame">
    <div class="chrome"><i></i><i></i><i></i>
      <span class="url">staging.niveshcopilot.com/v5/portfolio</span>
      <span class="nv-pill mint st">Live</span>
    </div>
    <div class="app">
      <div class="rail">
        <span class="nv-mark" style="width:30px;height:30px;font-size:18px">न</span>
        <span class="ico on">◧</span><span class="ico">◎</span><span class="ico">🎯</span><span class="ico">₹</span><span class="ico">⚑</span>
        <span class="sp"></span><span class="av">AP</span>
      </div>
      <div class="view">
        <div class="viewbar">
          <div class="vt">Portfolio</div>
          <div class="grow"></div>
          <span class="chip neutral">NAV updated 10:14 PM</span>
          <button class="nv-btn sm ghost">1Y ▾</button>
          <button class="nv-btn sm">Export</button>
        </div>
        <div class="viewbody">
          <div class="grid4">
            <div class="stat"><span class="k">Current value</span><span class="v serif num">₹ 62.4 L</span><span class="d pos">▲ ₹ 18,240 · 0.29% today</span></div>
            <div class="stat"><span class="k">Invested</span><span class="v num">₹ 48.9 L</span><span class="d muted">across 14 schemes</span></div>
            <div class="stat"><span class="k">Total gain</span><span class="v num pos">+₹ 13.5 L</span><span class="d pos">+27.6% absolute</span></div>
            <div class="stat"><span class="k">XIRR</span><span class="v num">14.2%</span><span class="d muted">since Jun 2021</span></div>
          </div>
          <div class="row" style="align-items:stretch">
            <div class="nv-card pad" style="flex:1;min-width:220px">
              <div class="ch"><span class="lbl">Allocation</span><span class="tag">look-through</span></div>
              <div class="row" style="align-items:center;gap:18px">
                <div class="donut" style="--sz:118px;--a:52%;--b:74%;--cc:90%;--c1:var(--mint);--c2:var(--indigo);--c3:var(--amber);--c4:var(--s4)"></div>
                <div class="legend">
                  <span class="li"><span class="sw" style="background:var(--mint)"></span>Equity <b class="num">&nbsp;52%</b></span>
                  <span class="li"><span class="sw" style="background:var(--indigo)"></span>Debt <b class="num">&nbsp;22%</b></span>
                  <span class="li"><span class="sw" style="background:var(--amber)"></span>Hybrid <b class="num">&nbsp;16%</b></span>
                  <span class="li"><span class="sw" style="background:var(--s4)"></span>Cash <b class="num">&nbsp;10%</b></span>
                </div>
              </div>
            </div>
            <div class="nv-card pad" style="flex:2;min-width:320px">
              <div class="ch"><span class="lbl">Holdings</span><span class="chip warn">1 needs attention</span></div>
              <div class="tbl-wrap"><table class="tbl">
                <thead><tr><th>Scheme</th><th class="r">Units</th><th class="r">NAV</th><th class="r">Value</th><th class="r">Gain</th><th class="r">XIRR</th></tr></thead>
                <tbody>
                  <tr><td><div class="nm">Parag Parikh Flexi Cap</div><div class="sub">Direct · Growth</div></td><td class="r num">812.4</td><td class="r num">78.21</td><td class="r num">₹ 6.35 L</td><td class="r num pos">+31%</td><td class="r num">16.1%</td></tr>
                  <tr><td><div class="nm">ICICI Pru Bluechip</div><div class="sub">Direct · Growth</div></td><td class="r num">1,204.0</td><td class="r num">98.44</td><td class="r num">₹ 11.85 L</td><td class="r num pos">+24%</td><td class="r num">13.4%</td></tr>
                  <tr><td><div class="nm">SBI Small Cap <span class="chip bad" style="margin-left:6px">Underperform</span></div><div class="sub">Direct · Growth</div></td><td class="r num">640.2</td><td class="r num">168.9</td><td class="r num">₹ 10.8 L</td><td class="r num neg">−4%</td><td class="r num neg">6.2%</td></tr>
                  <tr><td><div class="nm">UTI Nifty 50 Index</div><div class="sub">Direct · Growth</div></td><td class="r num">2,980.0</td><td class="r num">142.7</td><td class="r num">₹ 4.25 L</td><td class="r num pos">+12%</td><td class="r num">11.9%</td></tr>
                </tbody>
              </table></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</article>
```

## WORKED EXAMPLE B — form / step screen with states (copy this pattern)
```html
<article class="screen" id="ex-ekyc">
  <div class="cap">
    <span class="nv-pill indigo">New</span><h3>Aadhaar eKYC</h3>
    <span class="route">/v5/onboarding/ekyc</span><span class="nv-pill">⛓ UIDAI</span>
    <p class="desc">Real-time UIDAI OTP verification auto-fills identity in &lt;3s. FR-01-01.</p>
  </div>
  <div class="frame">
    <div class="chrome"><i></i><i></i><i></i>
      <span class="url">staging.niveshcopilot.com/v5/onboarding/ekyc</span>
      <span class="nv-pill indigo st">New</span>
    </div>
    <div class="app">
      <div class="rail"><span class="nv-mark" style="width:30px;height:30px;font-size:18px">न</span><span class="ico on">◎</span><span class="sp"></span><span class="av">AP</span></div>
      <div class="view">
        <div class="viewbar"><div class="vt">Open your account</div><div class="grow"></div><span class="chip info">Step 2 of 6</span></div>
        <div class="viewbody pad-lg">
          <!-- stepper -->
          <div class="seg"><span>eKYC</span><span class="on">Aadhaar</span><span>Risk</span><span>eSign</span><span>Mandate</span><span>Done</span></div>
          <div class="row" style="gap:22px;align-items:flex-start">
            <div class="col" style="flex:1;min-width:260px">
              <div class="field"><label>Aadhaar number</label><div class="input num">XXXX · XXXX · 1234</div></div>
              <div class="field"><label>UIDAI OTP</label><div class="input otp">● ● ● ● ● ●</div></div>
              <div class="between">
                <span class="muted" style="font-size:12px">Resend OTP in <b class="num">0:27</b></span>
                <button class="nv-btn primary">Verify identity</button>
              </div>
              <div class="banner ok"><span class="bi">✓</span><div>Aadhaar masked and <b>never stored</b> after verification · txn ref <span class="mono">UIDAI-8842…</span></div></div>
            </div>
            <div class="nv-card-2 pad" style="flex:1;min-width:260px">
              <div class="ch"><span class="lbl">Auto-populated from KYC</span><span class="chip ok">Verified</span></div>
              <div class="col" style="gap:10px">
                <div class="between"><span class="muted">Name</span><b>Aarav P. Sharma</b></div>
                <hr class="hair"><div class="between"><span class="muted">DOB</span><b class="num">14 Aug 1989</b></div>
                <hr class="hair"><div class="between"><span class="muted">Address</span><b style="text-align:right">Koregaon Park, Pune 411001</b></div>
              </div>
            </div>
          </div>
          <div class="banner warn"><span class="bi">!</span><div><b>UIDAI slow?</b> After 3 failed OTP attempts we switch you to manual KYC in under 5s — no restart needed.</div></div>
        </div>
      </div>
    </div>
  </div>
</article>
```

Match this quality bar. Each of your screens should look like a real page from a shipped fintech app.
