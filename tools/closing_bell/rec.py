"""Closing Bell — record the desk footage for each segment (CDP screencast, JPEG q92), timed to timeline.json.

Read-only: it navigates, hovers, scrolls, types into the Results-week search box and switches views / index
pickers / the cash-F&O toggle. It never clicks Paper trade, alerts, Ask, or anything that writes.
What it points at comes from the night's script: each beat's `focus` (symbols, search terms, index, macro
ids). Signs in as the Closing Bell bot (session token at /tok, created and revoked by the pipeline).

usage: python rec.py s1 [s2 ...]     writes /w/raw/<sid>/f*.jpg + index.json {frames, log, warm_error}
"""
import asyncio
import base64
import json
import os
import sys
import time

from playwright.async_api import async_playwright

TOK = open('/tok').read().strip()
HOST = os.environ.get('DESK_HOST', 'staging.niveshcopilot.com')
BASE = f'https://{HOST}/v5/app/trader/desk'
TL = json.load(open('/w/timeline.json'))
SEGS = {s['id']: s for s in json.load(open('/w/script.json'))['segments']}
CARDS = json.load(open('/w/cards.json'))
W, H = 1440, 810

CURSOR_JS = r"""
(() => { if (window.__curInit) return; window.__curInit = 1;
  const mk = () => { if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.style.cssText = 'position:fixed;z-index:2147483647;left:0;top:0;width:30px;height:30px;pointer-events:none;transform:translate(-100px,-100px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))';
    c.innerHTML = '<svg width="30" height="30" viewBox="0 0 24 24"><path d="M5 3l14 8-6 2-3 6z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    const r = document.createElement('div'); r.id = '__rip';
    r.style.cssText = 'position:fixed;z-index:2147483646;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:3px solid #2fe39b;pointer-events:none;opacity:0';
    document.documentElement.appendChild(r); };
  addEventListener('mousemove', e => { mk(); document.getElementById('__cur').style.transform = `translate(${e.clientX - 6}px,${e.clientY - 4}px)`; }, true);
  addEventListener('mousedown', e => { mk(); const r = document.getElementById('__rip'); r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    r.animate([{opacity: .95, transform: 'scale(.4)'}, {opacity: 0, transform: 'scale(1.8)'}], {duration: 550}); }, true);
})();
"""
MARK_JS = """() => { document.querySelectorAll('[data-scr]').forEach(e => e.removeAttribute('data-scr'));
  const els=[...document.querySelectorAll('*')].filter(e=>{const s=getComputedStyle(e);return (s.overflowY=='auto'||s.overflowY=='scroll')&&e.scrollHeight>e.clientHeight+150&&e.clientWidth>500});
  els.sort((a,b)=>b.scrollHeight-a.scrollHeight); const e=els[0]||document.scrollingElement; e.setAttribute('data-scr','1'); return [e.tagName, e.scrollHeight, e.clientHeight]; }"""
SCROLL_JS = """([y,dur]) => new Promise(res => { const c=document.querySelector('[data-scr]'); if(!c){res();return;}
  if (dur <= 0) { c.scrollTop = y; res(); return; }
  const y0=c.scrollTop, t0=performance.now();
  const f=(t)=>{ const k=Math.min(1,(t-t0)/(dur*1000)); const e=k<.5?4*k*k*k:1-Math.pow(-2*k+2,3)/2; c.scrollTop=y0+(y-y0)*e; if(k<1) requestAnimationFrame(f); else res(); };
  requestAnimationFrame(f); })"""
TOP_JS = """(sel) => { const e=document.querySelector(sel); const c=document.querySelector('[data-scr]'); if(!e||!c) return null;
  const r=e.getBoundingClientRect(), cr=c.getBoundingClientRect(); return {y: c.scrollTop + (r.top - cr.top), h: r.height, ctop: cr.top, ch: c.clientHeight}; }"""


def css(sym):
    return sym.replace('\\', '\\\\').replace('"', '\\"')


class Scene:
    def __init__(self, pg, sid):
        self.pg, self.sid = pg, sid
        self.B = [b['start'] for b in TL[sid]['beats']]
        self.beats = SEGS[sid]['beats']
        self.len = TL[sid]['len']
        self.x, self.y = 900.0, 450.0
        self.t0 = None
        self.log = []

    def T(self):
        return time.time() - self.t0 if self.t0 else -1

    def note(self, m):
        self.log.append([round(self.T(), 2), m])
        print(f'[{self.sid} {self.T():6.2f}] {m}', flush=True)

    async def until(self, t):
        d = t - self.T()
        if d > 0:
            await asyncio.sleep(d)

    async def at(self, i, off=0.0):
        await self.until(self.B[i] + off)

    def end_of(self, i):
        return self.B[i + 1] if i + 1 < len(self.B) else self.len

    async def move(self, x, y, dur=0.8):
        n = max(2, int(dur * 40))
        x0, y0 = self.x, self.y
        for k in range(1, n + 1):
            e = k / n
            e = e * e * (3 - 2 * e)
            await self.pg.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            await asyncio.sleep(dur / n)
        self.x, self.y = x, y

    async def box(self, sel):
        loc = self.pg.locator(sel).first
        try:
            if await loc.count() == 0 or not await loc.is_visible():
                return None
            return await loc.bounding_box()
        except Exception:
            return None

    async def hover(self, sel, dur=0.8, dx=0.5, dy=0.5, maxx=1000, scroll=True):
        b = await self.box(sel)
        if b and scroll and (b['y'] < 60 or b['y'] + b['height'] > H - 10):
            await self.scroll_to(sel, off=160, dur=0.9)
            b = await self.box(sel)
        if not b:
            self.note(f'hover: not visible {sel}')
            return False
        x = min(b['x'] + b['width'] * dx, maxx)
        y = b['y'] + b['height'] * dy
        if y < 60 or y > H - 10:
            self.note(f'hover: off screen {sel} y={y:.0f}')
            return False
        await self.move(x, y, dur)
        return True

    async def click(self, sel, dur=0.7):
        if await self.hover(sel, dur):
            await self.pg.mouse.down(); await asyncio.sleep(0.08); await self.pg.mouse.up()
            return True
        return False

    async def scroll(self, y, dur=1.2):
        await self.pg.evaluate(SCROLL_JS, [y, dur])

    async def scroll_to(self, sel, off=80, dur=1.2):
        await self.pg.evaluate(MARK_JS)
        r = await self.pg.evaluate(TOP_JS, sel)
        if r is None:
            self.note(f'scroll_to: missing {sel}')
            return None
        await self.scroll(max(0, r['y'] - off), dur)
        return r

    async def type(self, sel, text, delay=0.06):
        b = await self.box(sel)
        if not b:
            self.note(f'type: missing {sel}')
            return
        await self.move(b['x'] + 40, b['y'] + b['height'] / 2, 0.6)
        await self.pg.mouse.click(b['x'] + 40, b['y'] + b['height'] / 2)
        await self.pg.keyboard.press('Control+A'); await self.pg.keyboard.press('Backspace')
        for ch in text:
            await self.pg.keyboard.type(ch)
            await asyncio.sleep(delay)


# ------------------------------------------------------------------ warm-ups (load the screen before the clock starts)
async def goto(pg, url, wait_sel, timeout=90000):
    await pg.goto(url, wait_until='domcontentloaded')
    await pg.wait_for_timeout(1500)
    if '/login' in pg.url or '/onboarding' in pg.url:
        raise RuntimeError(f'LOGIN redirect to {pg.url}')
    await pg.wait_for_selector(wait_sel, timeout=timeout)
    await pg.wait_for_timeout(3000)


async def warm_overview(pg):
    await goto(pg, BASE + '?tab=overview', '[data-testid^="desk-top10-stock-"]')


async def warm_rw(pg):
    await goto(pg, BASE + '?tab=market&view=intel&section=events', '[data-testid="events-view-rw"]')
    await pg.locator('[data-testid="events-view-rw"]').first.scroll_into_view_if_needed()
    await pg.locator('[data-testid="events-view-rw"]').first.click()
    await pg.wait_for_selector('[data-testid="results-week-counts"]', timeout=90000)
    await pg.wait_for_timeout(3000)


async def warm_sectors(pg):
    await goto(pg, BASE + '?tab=market&view=sectors', '[data-testid="hm-treemap"]')


async def warm_sm(pg):
    await goto(pg, BASE + '?tab=market&view=smartmoney', '[data-testid="desk-smart-money-sector-bars"]')


async def warm_scanner(pg):
    await goto(pg, BASE + '?tab=trade&view=scanner&sub=ranked', '[data-testid^="desk-top10-stock-"]')


# ------------------------------------------------------------------ per-segment drivers (one action group per beat)
async def act_s1(s):
    await s.pg.evaluate(MARK_JS)
    ideas = [i['sym'] for i in CARDS.get('ideas') or []]
    for i, b in enumerate(s.beats):
        await s.at(i, 0.4)
        if i == 0:
            await s.hover('[data-testid="mo-sector-up"]', 1.2)
            await s.until(s.B[i] + 4.0); await s.hover('[data-testid="mo-sector-down"]', 1.0)
        elif b['card'] == 'idx':
            await s.hover('[data-testid="desk-top10-switch-stocks"]', 1.0)
            if ideas:
                await s.until(s.B[i] + 3.0); await s.hover(f'[data-testid="desk-top10-stock-{css(ideas[0])}"]', 1.0, dx=0.2)
        elif b['card'] == 'brd' and len(ideas) > 1:
            await s.hover(f'[data-testid="desk-top10-stock-{css(ideas[1])}"]', 1.0, dx=0.2)
        elif (b.get('focus') or {}).get('desk') == 'regime':
            await s.hover('[data-testid^="mo-regime-"]', 1.0)


async def rw_counts_view(s):
    await s.pg.evaluate(MARK_JS)
    r = await s.pg.evaluate(TOP_JS, '[data-testid="results-week-market"]')
    if r:
        await s.scroll(max(0, r['y'] - r['ch'] + 4), 0)


async def act_s2(s):
    await rw_counts_view(s)
    fno_on = False
    for i, b in enumerate(s.beats):
        f = b.get('focus') or {}
        await s.at(i, 0.3)
        if f.get('desk') == 'results':
            await s.hover('[data-testid="results-week-count-declared"]', 1.0)
            await s.until(s.B[i] + 3.0); await s.hover('[data-testid="results-week-count-upcoming"]', 1.0)
        elif b['card'] is None:
            await s.hover('[data-testid="results-week-basis"]', 1.0, dx=0.3)
            for k in ('above', 'in-line', 'below'):
                await s.hover(f'[data-testid="results-week-count-{k}"]', 0.6)
        elif b['card'] == 'res':
            names, syms = f.get('search') or [], f.get('syms') or []
            per = max(2.5, (s.end_of(i) - s.B[i] - 0.6) / max(1, len(names)))
            for k, (name, sym) in enumerate(zip(names, syms)):
                await s.until(s.B[i] + 0.3 + k * per)
                if k == 0:
                    await s.scroll_to('[data-testid="results-week-search"]', off=110, dur=0)
                await s.type('[data-testid="results-week-search"]', name.split()[0] if len(name) > 14 else name)
                await asyncio.sleep(1.0)
                if not await s.hover(f'[data-testid="results-week-reaction-{css(sym)}"]', 0.8, scroll=False):
                    await s.hover(f'[data-testid="results-week-row-{css(sym)}"]', 0.8, dx=0.25, scroll=False)
        elif b['card'] == 'after':
            if not fno_on:
                await s.type('[data-testid="results-week-search"]', '', 0)
                await s.click('[data-testid="results-week-universe-fno"]', 0.8)
                await asyncio.sleep(1.5); fno_on = True
            syms = f.get('syms') or []
            per = max(2.0, (s.end_of(i) - s.B[i] - 0.5) / max(1, len(syms)))
            for k, sym in enumerate(syms):
                await s.until(s.B[i] + 0.2 + k * per)
                await s.hover(f'[data-testid="results-week-row-{css(sym)}"]', 0.9, dx=0.25)


async def pick_index(s, code):
    sel = s.pg.locator('[data-testid="hm-index"] select, select[data-testid="hm-index"]').first
    if await sel.count() == 0:
        s.note('index select missing'); return
    b = await sel.bounding_box()
    if b:
        await s.move(b['x'] + b['width'] / 2, b['y'] + b['height'] / 2, 0.7)
        await s.pg.mouse.down(); await s.pg.mouse.up(); await asyncio.sleep(0.15)
    await sel.select_option(code)
    await s.pg.keyboard.press('Escape')
    try:
        await s.pg.wait_for_function("() => !document.querySelector('[data-testid=\"hm-loading\"]')", timeout=20000)
    except Exception:
        s.note('heatmap loading wait timed out')
    await asyncio.sleep(0.8)


async def act_s3(s):
    await s.pg.evaluate(MARK_JS); await s.scroll(0, 0)
    n50 = (CARDS.get('movers') or {}).get('Nifty 50') or {}
    for i, b in enumerate(s.beats):
        await s.at(i, 0.4)
        if i == 0:
            await s.hover('[data-testid="hm-verdict"]', 1.2, dx=0.3)
            await s.until(s.B[i] + 3.0); await s.scroll_to('[data-testid="hm-treemap"]', off=20, dur=1.6)
            for x in (n50.get('top') or [])[:2]:
                await s.hover(f'[data-testid="hm-tile-{css(x["sym"])}"]', 0.9, scroll=False)
        elif i == 1:
            for x in (n50.get('bottom') or [])[:2]:
                await s.hover(f'[data-testid="hm-tile-{css(x["sym"])}"]', 0.9, scroll=False)
        else:
            await s.scroll_to('[data-testid="hm-controls"]', off=60, dur=1.0)
            btn = s.pg.locator('[data-testid="hm-controls"] button', has_text='1M').first
            bb = await btn.bounding_box() if await btn.count() else None
            if bb:
                await s.move(bb['x'] + bb['width'] / 2, bb['y'] + bb['height'] / 2, 0.8)
                await s.pg.mouse.down(); await s.pg.mouse.up()
            await s.until(s.B[i] + max(3.0, (s.end_of(i) - s.B[i]) * 0.55))
            await s.scroll_to('[data-testid="hm-matrix"]', off=40, dur=1.6)
            await s.hover('[data-testid="hm-matrix"]', 1.0, dx=0.4, dy=0.25, scroll=False)


async def act_s4(s):
    await s.pg.evaluate(MARK_JS); await s.scroll_to('[data-testid="hm-controls"]', off=8, dur=0)
    current = 'NIFTY50'
    for i, b in enumerate(s.beats):
        f = b.get('focus') or {}
        await s.at(i, 0.2)
        if f.get('index') and f['index'] != current:
            await pick_index(s, f['index']); current = f['index']
        syms = f.get('syms') or []
        per = max(1.5, (s.end_of(i) - s.B[i] - 2.0) / max(1, len(syms)))
        for k, sym in enumerate(syms):
            await s.until(s.B[i] + 1.2 + k * per)
            await s.hover(f'[data-testid="hm-tile-{css(sym)}"]', 0.9, scroll=False)
        for name in f.get('sectors') or []:
            loc = s.pg.locator('[data-testid^="hm-sector-"]', has_text=name).first
            try:
                if await loc.count():
                    await s.pg.evaluate("(e) => e.setAttribute('data-sector-focus', '1')", await loc.element_handle())
                    await s.scroll_to('[data-sector-focus="1"]', off=220, dur=0.8)
                    await s.pg.evaluate("() => document.querySelectorAll('[data-sector-focus]').forEach(e => e.removeAttribute('data-sector-focus'))")
                bb = await loc.bounding_box() if await loc.count() else None
            except Exception:
                bb = None
            if bb and 60 < bb['y'] < H - 20:
                await s.move(bb['x'] + min(40, bb['width'] / 2), bb['y'] + 8, 0.9); await asyncio.sleep(1.0)
            else:
                s.note(f'sector header not visible {name}')


async def act_s5(s):
    await s.pg.evaluate(MARK_JS); await s.scroll(0, 0)
    await s.at(0, 0.5); await s.scroll(330, 1.4)
    await s.move(380, 300, 1.0); await asyncio.sleep(2.0); await s.move(560, 300, 0.8)
    if len(s.B) < 2:
        return
    await s.at(1, 0.0)
    try:
        r = await s.pg.evaluate("""() => { const e=[...document.querySelectorAll('*')].find(x=>x.childElementCount===0&&/Foreign institutions/.test(x.textContent)); if (e) e.scrollIntoView({block:'center'}); return !!e; }""")
        await s.pg.evaluate(MARK_JS)
        if not r:
            s.note('flows block not found')
    except Exception as e:
        s.note(f'flows block: {e}')
    await asyncio.sleep(0.6)
    boxes = await s.pg.evaluate("""() => [...document.querySelectorAll('svg')].map(e=>{const r=e.getBoundingClientRect(); return [r.x,r.y,r.width,r.height];}).filter(b=>b[2]>400&&b[3]>100&&b[1]>0&&b[1]<700)""")
    if boxes:
        x, y, w, h = boxes[0]
        await s.move(x + 10, y + h * 0.5, 0.8)
        steps = 40
        dt = max(0.08, min(0.2, (s.end_of(1) - s.T() - 1.0) / steps))
        for k in range(1, steps + 1):
            await s.pg.mouse.move(x + 10 + (w - 20) * k / steps, y + h * 0.5); s.x = x + 10 + (w - 20) * k / steps
            await asyncio.sleep(dt)
    else:
        s.note('flow chart svg not found')
    if len(s.B) > 2:
        await s.at(2, 0.3)
        await s.scroll_to('[data-testid="desk-smart-money-sector-totals"]', off=120, dur=1.6)
        await s.hover('[data-testid^="desk-smart-money-sector-row-"]', 1.0, dx=0.6, scroll=False)


async def act_s6(s):
    await s.pg.evaluate(MARK_JS); await s.scroll_to('[data-testid="desk-top10"]', off=10, dur=0)
    for i, b in enumerate(s.beats):
        f = b.get('focus') or {}
        await s.at(i, 0.4)
        if f.get('desk') == 'scanner':
            await s.hover('[data-testid="desk-top10-basis"]', 1.0, dx=0.3)
            await s.until(s.B[i] + 4.0); await s.hover('[data-testid="desk-top10-switch-stocks"]', 0.8)
        elif f.get('desk') == 'fno':
            await s.scroll_to('[data-testid="desk-top10"]', off=10, dur=1.2)
            await s.click('[data-testid="desk-top10-switch-fno"]', 0.8)
            await asyncio.sleep(2.0); await s.move(520, 420, 0.8)
            first = ((CARDS.get('fno') or [{}])[0]).get('sym')
            if first:
                loc = s.pg.locator('[data-testid="desk-top10"]').get_by_text(first, exact=True).first
                try:
                    if await loc.count():
                        await s.pg.evaluate("(e) => e.setAttribute('data-first-fno','1')", await loc.element_handle())
                        await s.until(s.B[i] + 5.0)
                        await s.scroll_to('[data-first-fno="1"]', off=140, dur=1.6); await s.hover('[data-first-fno="1"]', 0.8, scroll=False)
                except Exception as e:
                    s.note(f'fno row: {e}')
        else:
            syms = f.get('syms') or []
            per = max(0.9, (s.end_of(i) - s.B[i] - 0.6) / max(1, len(syms)))
            for k, sym in enumerate(syms):
                await s.until(s.B[i] + 0.2 + k * per)
                await s.hover(f'[data-testid="desk-top10-stock-{css(sym)}"]', min(0.8, per * 0.5), dx=0.2, dy=0.15)


async def act_s7(s):
    await rw_counts_view(s)
    for i, b in enumerate(s.beats):
        f = b.get('focus') or {}
        await s.at(i, 0.3)
        for k, mid in enumerate(f.get('macro') or []):
            await s.hover(f'[data-testid="results-week-macro-{css(mid)}"]', 1.0, dx=0.4, scroll=False)
            await asyncio.sleep(1.5)
        if f.get('search'):
            await s.scroll_to('[data-testid="results-week-search"]', off=110, dur=0)
            await s.type('[data-testid="results-week-search"]', f['search'][0])
            await asyncio.sleep(1.2); await s.move(560, 330, 1.0)


SCENES = {'s1': (warm_overview, act_s1), 's2': (warm_rw, act_s2), 's3': (warm_sectors, act_s3), 's4': (warm_sectors, act_s4),
          's5': (warm_sm, act_s5), 's6': (warm_scanner, act_s6), 's7': (warm_rw, act_s7)}


async def record(p, sid):
    warm, act = SCENES[sid]
    out = f'/w/raw/{sid}'
    os.makedirs(out, exist_ok=True)
    for fn in os.listdir(out):
        os.remove(os.path.join(out, fn))
    br = await p.chromium.launch()
    ctx = await br.new_context(viewport={'width': W, 'height': H}, device_scale_factor=1)
    await ctx.add_cookies([{'name': 'session_token', 'value': TOK, 'domain': HOST, 'path': '/', 'secure': True, 'httpOnly': True}])
    await ctx.add_init_script(CURSOR_JS)
    pg = await ctx.new_page()
    s = Scene(pg, sid)
    frames = []
    warm_error = None
    try:
        await warm(pg)
    except Exception as e:  # noqa: BLE001 — reported to checks.py, which holds the edition
        warm_error = f'{type(e).__name__}: {str(e)[:160]}'
        print(f'{sid}: WARM FAILED {warm_error}', flush=True)
    cdp = await ctx.new_cdp_session(pg)

    async def on_frame(ev):
        ts = ev['metadata'].get('timestamp') or time.time()
        fn = f'f{len(frames):05d}.jpg'
        open(f'{out}/{fn}', 'wb').write(base64.b64decode(ev['data']))
        frames.append({'ts': ts, 'f': fn})
        try:
            await cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
        except Exception:
            pass
    cdp.on('Page.screencastFrame', lambda ev: asyncio.ensure_future(on_frame(ev)))
    await cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': W, 'maxHeight': H, 'everyNthFrame': 1})
    await pg.mouse.move(s.x, s.y)
    s.t0 = time.time()
    await pg.mouse.move(s.x + 1, s.y + 1)
    if not warm_error:
        try:
            await act(s)
        except Exception as e:  # noqa: BLE001
            s.note(f'ACTION ERROR {type(e).__name__}: {e}')
    await s.until(s.len + 0.6)
    await cdp.send('Page.stopScreencast')
    await asyncio.sleep(0.5)
    idx = [{'t': round(fr['ts'] - s.t0, 3), 'f': fr['f']} for fr in frames]
    json.dump({'sid': sid, 'len': s.len, 'frames': idx, 'log': s.log, 'warm_error': warm_error}, open(f'{out}/index.json', 'w'))
    print(f'{sid}: {len(idx)} frames, misses {sum("not visible" in m or "missing" in m for _, m in s.log)}', flush=True)
    await br.close()


async def main():
    async with async_playwright() as p:
        for sid in sys.argv[1:]:
            if sid in SEGS and sid in SCENES:
                await record(p, sid)

asyncio.run(main())
