"""Closing Bell — render every broadcast graphic from gfx.html as PNGs (cards as 36-frame entry animations).
Runs in the closing-bell tools image with the night's work dir at /w and this folder at /app.
usage: python gfx.py [only-kind ...]"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

W = '/w'
OUT = f'{W}/gfx'
os.makedirs(OUT, exist_ok=True)
D = json.load(open(f'{W}/cards.json'))
SCRIPT = json.load(open(f'{W}/script.json'))
SC = SCRIPT['segments']
HEADS = SCRIPT.get('headlines') or []
BOX = {'idx', 'brd', 'res', 'after', 'sec', 'n50', 'n100', 'n200', 'n500', 's500', 'fii', 'ideas', 'fno', 'watch'}
FULL = {'title', 'h1', 'h2', 'h3', 'h4', 'end'}
NF = 36  # 1.44 s of entry animation at 25 fps, then the last frame holds
only = set(sys.argv[1:])
want = lambda k: not only or k in only
cards = sorted({b['card'] for s in SC for b in s['beats'] if b['card']})

with sync_playwright() as p:
    br = p.chromium.launch()
    pg = br.new_page(viewport={'width': 1920, 'height': 1080})
    pg.goto('file:///app/gfx.html')
    pg.wait_for_function('document.fonts.status === "loaded"')
    pg.evaluate('document.fonts.ready')

    def render(kind, spec, w, h):
        pg.set_viewport_size({'width': w, 'height': h})
        pg.evaluate('([k, d, s]) => window.render(k, d, s)', [kind, D, dict(spec, w=w, h=h)])
        pg.evaluate('document.fonts.ready')

    def frames(name, kind, spec, w, h, n=NF):
        d = f'{OUT}/{name}'
        os.makedirs(d, exist_ok=True)
        render(kind, spec, w, h)
        for i in range(n):
            pg.evaluate(f'window.setT({i / 25:.3f})')
            pg.screenshot(path=f'{d}/f{i:03d}.png', omit_background=True)
        print('frames', name, n, flush=True)

    if want('bg'):
        render('bg', {}, 1920, 1080)
        pg.screenshot(path=f'{OUT}/bg.png')
    for i, s in enumerate(SC):
        if want('frame'):
            render('frame', {'tag': s['tag'], 'title': s['title']}, 1920, 1080)
            pg.evaluate('window.setT(9)')
            pg.screenshot(path=f"{OUT}/frame_{s['id']}.png", omit_background=True)
        if want('sup'):
            for j, b in enumerate(s['beats']):
                render('sup', {'who': b['who'], 'tag': s['tag'], 'sup': b['sup']}, 1920, 1080)
                pg.screenshot(path=f"{OUT}/sup_{s['id']}_{j}.png", omit_background=True,
                              clip={'x': 0, 'y': 950, 'width': 1920, 'height': 72})
        if want('stinger') and s['id'] != 's0':
            frames(f"stinger_{s['id']}", 'stinger', {'num': f'{i:02d} / {len(SC) - 1:02d}', 'tag': s['tag'], 'title': s['title']}, 1536, 864, 34)
    if want('ticker'):
        render('ticker', {}, 20000, 56)
        L = pg.evaluate("document.getElementById('tkA').getBoundingClientRect().width")
        pg.screenshot(path=f'{OUT}/ticker.png', omit_background=True, clip={'x': 0, 'y': 0, 'width': int(2 * L) + 2, 'height': 56})
        json.dump({'L': L}, open(f'{OUT}/ticker.json', 'w'))
    for c in cards:
        if not want(c) and not want('cards'):
            continue
        if c in BOX:
            frames(f'card_{c}', c, {}, 440, 840)
        elif c in ('h1', 'h2', 'h3', 'h4'):
            k = int(c[1]) - 1
            if k < len(HEADS):
                frames(f'card_{c}', c, dict(HEADS[k], of=len(HEADS)), 1536, 864)
        elif c in FULL:
            frames(f'card_{c}', c, {}, 1536, 864)
    br.close()
    print('gfx done', flush=True)
