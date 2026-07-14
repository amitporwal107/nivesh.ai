#!/usr/bin/env python3
"""Generate a cinematic, self-contained product-tour page from the real V5 screens.
Dark committed stage (single-theme, by design) with the light-theme app screens
floating on it. Autoplays on a timeline; also has a player UI for the interactive
version. Recorded to video by record_tour.js."""
import re, sys

BASE = "/app/.claude/workspace/advisory-workflows"
KIT  = f"{BASE}/kit"
OUT  = f"{BASE}/tour.html"

def read(p):
    with open(p, encoding="utf-8") as f: return f.read()

fonts = read(f"{KIT}/fonts.css")
kit   = read(f"{KIT}/v5-kit.css")

# --- light-token scope so embedded screens always render in the light V5 theme,
#     regardless of the (committed-dark) stage or the viewer's OS preference ---
LIGHT_SCOPE = """
.light-scope{
  --bg:#F6F4ED; --s1:#FFFFFF; --s2:#F1EEE3; --s3:#E7E3D4; --s4:#DAD5C2;
  --ink:#12100A; --ink2:#46412F; --ink3:#7A745E; --ink4:#A39B82; --ink5:#CFC9B5;
  --mint:#0E8A55; --mint2:#146B45; --mint-soft:rgba(14,138,85,.10);
  --amber:#B86A12; --amber-soft:rgba(184,106,18,.12);
  --indigo:#4F58D6; --indigo-soft:rgba(79,88,214,.10);
  --danger:#C5303E; --danger-soft:rgba(197,48,62,.09);
  --pos:#0E8A55; --neg:#C5303E;
  --line:rgba(20,18,12,.07); --line2:rgba(20,18,12,.13); --line3:rgba(20,18,12,.22);
  --shadow:0 1px 0 rgba(255,255,255,.5) inset, 0 20px 44px -26px rgba(20,18,12,.34);
  color:var(--ink);
}
"""

# extract a hero screen's <article> block from a fragment file (the .cap is hidden by tour CSS)
def hero(frag_id, screen_id):
    src = read(f"{BASE}/screens/{frag_id}.html")
    m = re.search(r'(<article class="screen" id="%s".*?</article>)' % re.escape(screen_id), src, re.S)
    if not m:
        sys.exit(f"HERO NOT FOUND: {screen_id} in {frag_id}.html")
    return m.group(1)

# workflow scenes: (num, kicker, title, valueprop, [callouts], status, screen frag+id)
WF = [
 ("01","Client Onboarding","Onboard in minutes,\nnot days.","A frictionless, compliant account-opening rail — from PAN to first SIP.",
   ["Aadhaar eKYC · auto-fills identity in under 3s","eSign + eMandate in one session","Live pipeline board for the advisor"],"New · vendor-gated","wf01","wf01-ekyc"),
 ("02","Goal-Based Planning","Every rupee\nhas a goal.","Turn analytics into “start this SIP”, with the maths already DB-backed.",
   ["Goal library + custom goals","SIP & 3-scenario return modeller","On-track / behind, at a glance"],"Live engine","wf02","wf02-dashboard"),
 ("03","Product Advisory","One research\nlanguage.","A single shelf and one score across every product you advise on.",
   ["Nivesh Research Score → stars + badge","Compare up to 3 funds side-by-side","Suitability-filtered, override logged"],"Live + Extend","wf03","wf03-shelf"),
 ("04","Portfolio Monitoring","Proactive,\nnot reactive.","Strong analytics wired to a scheduler so alerts actually fire.",
   ["Live XIRR + look-through allocation","Drift & underperformer alerts","One-click rebalance with tax flags"],"Live","wf04","wf04-portfolio"),
 ("05","Transaction & Reporting","Execute and report,\nend to end.","The transactional core — orders in, branded statements out.",
   ["BSE STAR order console + cut-off","SIP, step-up & bulk orders","Branded, reconciled statements"],"New · vendor-gated","wf05","wf05-order"),
 ("06","Compliance Automation","Compliant\nby construction.","License-to-operate, built into every transaction.",
   ["Fail-closed WORM audit trail","ARN + KYC status monitoring","SEBI disclosures, versioned"],"New","wf06","wf06-audit"),
 ("07","Engagement & Marketing","Grow your\npractice.","White-label brand, one-click comms, and the analytics to act.",
   ["White-label branding & domain","One-click client communication","Business + HNI analytics"],"Live + New","wf07","wf07-business"),
]

def scene_html(w):
    num,kicker,title,vp,callouts,status,frag,sid = w
    cos = "\n".join(
      f'<div class="callout" style="--i:{k}"><span class="cdot"></span>{c}</div>'
      for k,c in enumerate(callouts))
    title_html = title.replace("\n","<br>")
    return f'''<section class="scene wf" data-dur="6200">
  <div class="left">
    <div class="kicker"><span class="knum">{num}</span> Workflow</div>
    <h2 class="stitle">{title_html}</h2>
    <p class="svp">{vp}</p>
    <div class="callouts">{cos}</div>
    <div class="sstatus"><span class="sdot"></span>{status}</div>
  </div>
  <div class="right">
    <div class="deviceglow"></div>
    <div class="light-scope device">{hero(frag,sid)}</div>
  </div>
</section>'''

scenes = []
# intro
scenes.append('''<section class="scene intro" data-dur="4600">
  <div class="introwrap">
    <div class="bigmark">न</div>
    <div class="brandline">Nivesh</div>
    <h1 class="introtitle">Advisory,<br>end to end.</h1>
    <p class="introsub">One platform · seven workflows · forty-six screens</p>
  </div>
</section>''')
# workflows
for w in WF: scenes.append(scene_html(w))
# outro
scenes.append('''<section class="scene outro" data-dur="6000">
  <div class="introwrap">
    <div class="outrostat"><span>7</span> workflows &nbsp;·&nbsp; <span>46</span> screens &nbsp;·&nbsp; <span>1</span> platform</div>
    <h1 class="introtitle">Advise, transact and grow —<br>in one place.</h1>
    <div class="cta">Book a demo</div>
    <p class="introsub" style="margin-top:26px">Nivesh · SEBI Registered · ARN-115287</p>
  </div>
</section>''')

# chapter dots
CH = ["Intro","Onboarding","Planning","Advisory","Monitoring","Transactions","Compliance","Engagement","Overview"]
dots = "".join(f'<button class="dot" data-i="{i}" title="{c}"></button>' for i,c in enumerate(CH))

TOUR_CSS = """
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#04060C;overflow:hidden}
.tour{position:relative;width:1280px;height:720px;margin:0 auto;overflow:hidden;
  background:
    radial-gradient(900px 620px at 82% -8%, rgba(106,240,168,.16), transparent 60%),
    radial-gradient(820px 700px at 6% 108%, rgba(255,181,71,.10), transparent 60%),
    linear-gradient(180deg,#080B14,#04060C);
  color:#F5F7FF;font-family:var(--sans);letter-spacing:-.01em;
  transform-origin:top center;}
.tour::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(120% 120% at 50% 50%, transparent 62%, rgba(0,0,0,.45));}
/* subtle grain-free vignette handled above */

.scene{position:absolute;inset:0;opacity:0;visibility:hidden;transition:opacity .5s ease;
  padding:64px 72px;display:flex;align-items:center;gap:40px}
.scene.active{opacity:1;visibility:visible}
.scene .cap{display:none!important}   /* hide the spec caption from the source screens */

/* ---- intro / outro ---- */
.intro,.outro{justify-content:center;text-align:center}
.introwrap{max-width:900px;display:flex;flex-direction:column;align-items:center}
.bigmark{font-family:var(--display);width:96px;height:96px;border-radius:24px;display:grid;place-items:center;
  font-size:60px;color:#04120B;background:linear-gradient(140deg,#6AF0A8,#36C57E);
  box-shadow:0 20px 60px -18px rgba(106,240,168,.6);opacity:0;transform:scale(.6) translateY(12px)}
.intro.active .bigmark{animation:pop .9s cubic-bezier(.2,1,.3,1) .1s both}
.brandline{font-family:var(--display);font-size:30px;margin-top:20px;opacity:0}
.intro.active .brandline{animation:rise .8s ease .5s both}
.introtitle{font-family:var(--display);font-weight:400;font-size:82px;line-height:1.02;letter-spacing:-.02em;margin:8px 0 0;opacity:0}
.intro.active .introtitle{animation:rise 1s ease .8s both}
.outro.active .introtitle{animation:rise 1s ease .5s both}
.introsub{font-size:19px;color:#9AA6C4;margin-top:22px;opacity:0;font-family:var(--mono);letter-spacing:.02em}
.intro.active .introsub{animation:rise .9s ease 1.3s both}
.outrostat{font-size:20px;color:#9AA6C4;opacity:0;font-family:var(--mono);letter-spacing:.04em;margin-bottom:14px}
.outrostat span{color:#6AF0A8;font-family:var(--display);font-size:30px;vertical-align:-3px}
.outro.active .outrostat{animation:rise .8s ease .2s both}
.cta{margin-top:30px;padding:14px 30px;border-radius:14px;background:#6AF0A8;color:#04120B;font-weight:600;font-size:16px;opacity:0;box-shadow:0 16px 40px -14px rgba(106,240,168,.6)}
.outro.active .cta{animation:pop .8s cubic-bezier(.2,1,.3,1) 1.1s both}

/* ---- workflow split scene ---- */
.wf .left{width:34%;flex:none;z-index:2}
.wf .right{flex:1;position:relative;height:100%;display:flex;align-items:center;justify-content:center;min-width:0;overflow:hidden}
.kicker{font-family:var(--mono);font-size:13px;letter-spacing:.16em;text-transform:uppercase;color:#7A879F;
  display:flex;align-items:center;gap:10px;opacity:0}
.knum{color:#6AF0A8;font-size:15px}
.wf.active .kicker{animation:rise .7s ease .15s both}
.stitle{font-family:var(--display);font-weight:400;font-size:50px;line-height:1.03;letter-spacing:-.02em;margin:16px 0 0;opacity:0}
.wf.active .stitle{animation:rise .8s ease .3s both}
.svp{font-size:17px;color:#AEB8D4;line-height:1.5;margin:18px 0 0;max-width:38ch;opacity:0}
.wf.active .svp{animation:rise .8s ease .5s both}
.callouts{margin-top:26px;display:flex;flex-direction:column;gap:11px}
.callout{display:flex;align-items:center;gap:11px;font-size:15px;color:#E6EAF6;
  background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);border-radius:12px;
  padding:11px 14px;opacity:0;backdrop-filter:blur(4px)}
.wf.active .callout{animation:slidein .7s cubic-bezier(.2,1,.3,1) calc(.75s + var(--i)*.28s) both}
.cdot{width:8px;height:8px;border-radius:50%;background:#6AF0A8;flex:none;box-shadow:0 0 10px rgba(106,240,168,.8)}
.sstatus{margin-top:22px;display:inline-flex;align-items:center;gap:9px;font-family:var(--mono);font-size:11px;
  letter-spacing:.1em;text-transform:uppercase;color:#8892AC;opacity:0}
.sdot{width:7px;height:7px;border-radius:50%;background:#8E97FF}
.wf.active .sstatus{animation:rise .7s ease 1.5s both}

/* floating device — centered in the right column, fully visible (no edge crop) */
.device{position:absolute;width:880px;left:50%;top:50%;
  transform:translate(-50%,-50%) scale(.74);transform-origin:center center;
  border-radius:16px;box-shadow:0 40px 92px -34px rgba(0,0,0,.85), 0 0 0 1px rgba(255,255,255,.06);
  opacity:0}
.wf.active .device{animation:wfdevice 6.6s cubic-bezier(.2,.7,.3,1) .3s both}
.deviceglow{position:absolute;width:660px;height:660px;left:50%;top:50%;transform:translate(-50%,-50%);
  background:radial-gradient(circle, rgba(106,240,168,.16), transparent 62%);filter:blur(34px);opacity:0}
.wf.active .deviceglow{animation:rise 1.2s ease .3s both}
.device .frame{border-color:rgba(255,255,255,.10)}

@keyframes pop{from{opacity:0;transform:scale(.6) translateY(12px)}to{opacity:1;transform:scale(1) translateY(0)}}
@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
@keyframes slidein{from{opacity:0;transform:translateX(-18px)}to{opacity:1;transform:translateX(0)}}
@keyframes wfdevice{
  0%{opacity:0;transform:translate(-50%,-50%) scale(.70)}
  16%{opacity:1}
  100%{opacity:1;transform:translate(-50.5%,-51%) scale(.765)}
}

/* ---- player chrome (hidden in record mode via ?chrome=0) ---- */
.player{position:absolute;left:0;right:0;bottom:0;z-index:20;display:flex;align-items:center;gap:16px;
  padding:14px 22px;background:linear-gradient(0deg, rgba(4,6,12,.9), transparent);}
.player button{background:none;border:none;color:#C6CEE4;cursor:pointer;font-size:15px;display:grid;place-items:center;padding:6px}
.player .pp{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.1);color:#fff}
.progress{flex:1;height:4px;border-radius:99px;background:rgba(255,255,255,.14);position:relative;overflow:hidden}
.progress > i{position:absolute;left:0;top:0;bottom:0;width:0;background:#6AF0A8;border-radius:99px}
.dots{display:flex;gap:7px}
.dot{width:9px;height:9px;border-radius:50%;background:rgba(255,255,255,.22);border:none;cursor:pointer;padding:0}
.dot.on{background:#6AF0A8}
.brandtag{font-family:var(--display);font-size:15px;color:#C6CEE4;margin-left:4px}
body.norecord .player{display:none}

/* fit-to-viewport for the interactive artifact (scaled down on smaller screens) */
@media (max-width:1279px){ .tour{transform:scale(calc(100vw/1280));} }
"""

TOUR_JS = """
(function(){
  var q=new URLSearchParams(location.search);
  var chrome = q.get('chrome')!=='0';
  var autoplay = q.get('autoplay')!=='0';
  var norepeat = q.get('norepeat')==='1';
  if(!chrome) document.body.classList.add('norecord');
  var scenes=[].slice.call(document.querySelectorAll('.scene'));
  var durs=scenes.map(function(s){return +s.dataset.dur;});
  var total=durs.reduce(function(a,b){return a+b;},0);
  var bar=document.querySelector('.progress > i');
  var dots=[].slice.call(document.querySelectorAll('.dot'));
  var ppBtn=document.querySelector('.pp');
  var i=-1, timer=null, playing=autoplay, done=false;
  function cum(n){var s=0;for(var k=0;k<n;k++)s+=durs[k];return s;}
  function paintBar(n){ if(!bar)return;
    bar.style.transition='none'; bar.style.width=(cum(n)/total*100)+'%';
    // next frame: animate to end of this scene
    requestAnimationFrame(function(){ requestAnimationFrame(function(){
      if(!playing)return;
      bar.style.transition='width '+durs[n]+'ms linear';
      bar.style.width=(cum(n+1)/total*100)+'%';
    });});
  }
  function show(n){
    scenes.forEach(function(s,k){s.classList.toggle('active',k===n);});
    dots.forEach(function(d,k){d.classList.toggle('on',k===n);});
    i=n; paintBar(n);
  }
  function schedule(){ clearTimeout(timer); if(!playing)return; timer=setTimeout(nextAuto, durs[i]); }
  function nextAuto(){
    if(i>=scenes.length-1){ if(norepeat){finish();return;} show(0); } else { show(i+1); }
    schedule();
  }
  function finish(){ done=true; playing=false; if(bar){bar.style.width='100%';} window.__tourDone=true; }
  function go(n){ n=Math.max(0,Math.min(scenes.length-1,n)); show(n); if(playing) schedule(); }
  function toggle(){ playing=!playing; if(ppBtn)ppBtn.textContent=playing?'❚❚':'▶';
    if(playing){ paintBar(i); schedule(); } else { clearTimeout(timer); if(bar){var w=getComputedStyle(bar).width;bar.style.transition='none';bar.style.width=w;} } }
  // controls
  if(chrome){
    ppBtn&&ppBtn.addEventListener('click',toggle);
    var prev=document.querySelector('.prev'), next=document.querySelector('.next'), rst=document.querySelector('.restart');
    prev&&prev.addEventListener('click',function(){go(i-1);});
    next&&next.addEventListener('click',function(){go(i+1);});
    rst&&rst.addEventListener('click',function(){done=false;playing=true;if(ppBtn)ppBtn.textContent='❚❚';go(0);});
    dots.forEach(function(d){d.addEventListener('click',function(){done=false;playing=true;if(ppBtn)ppBtn.textContent='❚❚';go(+d.dataset.i);});});
  }
  // kick off
  window.__tourTotalMs=total;
  show(0); if(playing) schedule();
})();
"""

PLAYER = f'''<div class="player">
  <button class="pp" aria-label="Play/pause">❚❚</button>
  <button class="prev" aria-label="Previous">⏮</button>
  <button class="next" aria-label="Next">⏭</button>
  <div class="progress"><i></i></div>
  <div class="dots">{dots}</div>
  <button class="restart" aria-label="Restart">↻</button>
  <span class="brandtag">Nivesh</span>
</div>'''

html = f'''<meta charset="utf-8">
<style>
{fonts}
{kit}
{LIGHT_SCOPE}
{TOUR_CSS}
</style>

<div class="tour">
{"".join(scenes)}
{PLAYER}
</div>
<script>
{TOUR_JS}
</script>'''

open(OUT,"w",encoding="utf-8").write(html)
print(f"WROTE {OUT} — {len(html):,} bytes · {len(scenes)} scenes · total {sum(int(s.split('data-dur=')[1][1:5]) for s in scenes)/1000:.0f}s")
