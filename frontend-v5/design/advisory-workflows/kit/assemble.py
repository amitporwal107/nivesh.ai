#!/usr/bin/env python3
"""Stitch the shared V5 kit + the 7 per-workflow fragments into one artifact,
validating tag balance and self-containment along the way."""
import re, html.parser, sys, os

BASE = "/app/.claude/workspace/advisory-workflows"
KIT  = f"{BASE}/kit"
OUT  = f"{BASE}/screen-designs-v5.html"

WF = [
  ("wf01","WF-01","Client Onboarding","Turn a lead into a KYC-verified, mandate-active investor. Only Risk Profiling is live today; the regulated rails are greenfield and vendor-gated."),
  ("wf02","WF-02","Goal-Based Planning","The maths is already correct and DB-backed — these screens add the library, capture, modeller, basket, dashboard and branded PDF around it."),
  ("wf03","WF-03","Product Advisory","One research language across products. MF universe, scoring and suitability are live; the six non-MF shelves are each a partner-gated mini-project."),
  ("wf04","WF-04","Portfolio Monitoring & Rebalancing","Strong analytics — XIRR, drift, switch-decision, FIFO cap-gains — wired to a scheduler + dispatcher so monitoring actually runs and alerts fire."),
  ("wf05","WF-05","Transaction & Reporting","The transactional core. Branded reports can ship internally; the BSE STAR/MFU order gateway is the big vendor-gated keystone."),
  ("wf06","WF-06","Compliance Automation","License-to-operate: a fail-closed WORM audit, ARN validation, KYC monitoring and SEBI disclosure acknowledgement."),
  ("wf07","WF-07","Client Engagement & Marketing","Why an MFD chooses the platform. A live Business Dashboard today; the comms dispatcher unblocks most of the rest."),
]

VOID = {"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}
def check_balance(src, label):
    stack, errs = [], []
    class V(html.parser.HTMLParser):
        def handle_starttag(self,t,a):
            if t not in VOID: stack.append(t)
        def handle_startendtag(self,t,a): pass
        def handle_endtag(self,t):
            if t in VOID: return
            if not stack or stack[-1]!=t: errs.append(f"{label}: mismatch </{t}> near {stack[-3:]}")
            elif stack: stack.pop()
    V().feed(src)
    if stack: errs.append(f"{label}: unclosed {stack[-5:]}")
    return errs

def read(p):
    with open(p, encoding="utf-8") as f: return f.read()

# --- gather fragments ---
fonts = read(f"{KIT}/fonts.css")
kit   = read(f"{KIT}/v5-kit.css")
errors, total_screens, frags = [], 0, {}
for wid,_,_,_ in WF:
    p = f"{BASE}/screens/{wid}.html"
    if not os.path.exists(p) or os.path.getsize(p)==0:
        errors.append(f"MISSING/empty fragment: {wid}.html"); frags[wid]=""; continue
    body = read(p).strip()
    body = re.sub(r"^```[a-z]*\n?","",body); body = re.sub(r"\n?```$","",body)  # strip stray fences
    n = body.count('class="screen"')
    total_screens += n
    forbidden = re.findall(r'<(?:style|script|link|img)\b|(?:src|href)\s*=\s*["\']https?://|url\(\s*https?://', body)
    if forbidden: errors.append(f"{wid}: forbidden asset/tag -> {forbidden[:3]}")
    errors += check_balance(body, wid)
    frags[wid] = body
    print(f"  {wid}: {n} screens, {len(body):,} bytes")

PAGE_CSS = """
.masthead{position:sticky;top:0;z-index:40;background:rgba(246,244,237,.86);backdrop-filter:blur(9px);border-bottom:1px solid var(--line);}
:root[data-theme="dark"] .masthead{background:rgba(6,8,15,.86)}
@media (prefers-color-scheme:dark){.masthead{background:rgba(6,8,15,.86)}}
.masthead .in{max-width:1240px;margin:0 auto;padding:13px 22px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.masthead .lg{display:flex;gap:13px;margin-left:auto;font-size:11.5px;color:var(--ink3);flex-wrap:wrap}
.masthead .lg .i{display:inline-flex;align-items:center;gap:6px}
.sw{width:9px;height:9px;border-radius:50%}
.intro{padding:46px 0 8px}
.intro .stat-row{display:flex;gap:11px;flex-wrap:wrap;margin-top:24px}
.intro .stat{min-width:118px}
.wfsec{padding:40px 0 6px;border-top:1px solid var(--line);margin-top:26px}
.wfsec .hd{margin-bottom:20px}
.wfsec .hd .tag{font-family:var(--sans);text-transform:none;letter-spacing:normal;background:none;color:var(--ink2);font-size:14.5px;padding:0;display:block;max-width:80ch;margin-top:8px}
.foot{border-top:1px solid var(--line);margin-top:44px;padding:24px 0 60px;color:var(--ink3);font-size:12.5px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
"""

# status split (design-level estimate)
head = f"""<style>
{fonts}
{kit}
{PAGE_CSS}
</style>

<header class="masthead"><div class="in">
  <span class="nv-mark">न</span>
  <b style="font-family:var(--display);font-size:19px;letter-spacing:-.01em">Nivesh · Advisory Workflows</b>
  <span class="mono" style="font-size:11px;color:var(--ink3)">V5 screen designs · WF-01 → WF-07</span>
  <span class="lg">
    <span class="i"><span class="sw" style="background:var(--mint)"></span>Live</span>
    <span class="i"><span class="sw" style="background:var(--amber)"></span>Extend</span>
    <span class="i"><span class="sw" style="background:var(--indigo)"></span>New</span>
    <span class="i" style="color:var(--indigo)">⛓ vendor-gated</span>
  </span>
  <button id="themeBtn" class="nv-btn sm" style="margin-left:12px" aria-label="Toggle dark mode">🌙 Dark</button>
</div></header>
<script>
(function(){{
  var r=document.documentElement, b=document.getElementById('themeBtn');
  function eff(){{return r.getAttribute('data-theme') || (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark':'light');}}
  function paint(t){{b.textContent = (t==='dark' ? '☀\\uFE0E Light' : '🌙 Dark');}}
  paint(eff());
  b.addEventListener('click', function(){{ var t = eff()==='dark' ? 'light':'dark'; r.setAttribute('data-theme', t); paint(t); }});
}})();
</script>

<div class="framewrap">
  <section class="intro">
    <p class="eyebrow">High-fidelity · real V5 design system</p>
    <h1 class="title">The 7 advisory workflows,<br>designed screen by screen.</h1>
    <p class="lede">Every screen rendered in Nivesh's real V5 language — Instrument Serif display, Inter Tight body, the live token palette and component kit — with realistic data and key states. Status colours come from the implementation audit, not a claim that a screen is fully built.</p>
    <div class="stat-row">
      <div class="stat"><span class="k">Screens</span><span class="v serif num">{total_screens}</span></div>
      <div class="stat"><span class="k">Live</span><span class="v num" style="color:var(--mint)">5</span></div>
      <div class="stat"><span class="k">Extend</span><span class="v num" style="color:var(--amber)">19</span></div>
      <div class="stat"><span class="k">New</span><span class="v num" style="color:var(--indigo)">22</span></div>
      <div class="stat"><span class="k">Workflows</span><span class="v serif num">7</span></div>
    </div>
  </section>
"""

sections = []
for wid,code,name,tag in WF:
    sections.append(f"""  <section class="wfsec" id="{wid}">
    <div class="hd">
      <div class="wf-eyebrow">Workflow · {code}</div>
      <h2 class="wf-title">{name}</h2>
      <span class="tag">{tag}</span>
    </div>
{frags.get(wid,'')}
  </section>""")

foot = """  <div class="foot">
    <div>Designed in the real V5 kit (<span class="mono">kit/v5-kit.css</span> · fonts inlined). Status reflects the FR audit in <span class="mono">.claude/workspace/advisory-workflows/</span>. Mockups use realistic sample data, not live production data.</div>
    <div class="mono">Nivesh · ARN-115287</div>
  </div>
</div>"""

final = head + "\n".join(sections) + "\n" + foot

# --- validate assembled page ---
errors += check_balance(final, "ASSEMBLED")
open(OUT,"w",encoding="utf-8").write(final)
print(f"\nWROTE {OUT} — {len(final):,} bytes · {total_screens} screens")
if errors:
    print("VALIDATION: FAIL"); [print("  -",e) for e in errors[:20]]; sys.exit(1)
print("VALIDATION: PASS (tag-balanced, self-contained, all fragments present)")
