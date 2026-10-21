import json,sys
r=json.load(open(sys.argv[1] if len(sys.argv)>1 else 'report.json'))
print(r['blocks']); print('adjustments',r['adjustments'] if not isinstance(r['adjustments'],dict) else {k:(v if k!='symbols_cut' else len(v)) for k,v in r['adjustments'].items()}, 'selected', r['selected_variant_train_validation_h10_15pct'])
cols=['n','dates','mean_gross','mean_net','mean_universe_gross','mean_excess_net','mean_excess_net_ci95','win_rate_net','hit5_pct','hit10_pct','mae_median','invalidation_hit_pct']
def row(name,s): print(f"{name:30}", *[f"{s.get(c)!s:>13}" for c in cols])
print(f"{'':30}", *[f"{c[:13]:>13}" for c in cols])
for v,d in r['results'].items():
    for p in ([None] if v=='momentum_continuation' else ['10.0','15.0','20.0']):
        x=d if p is None else d[p]
        for h in ('h5','h10','h20'): row(f"{v[:20]} {p or ''} {h}", x['all'][h]['base'])
print('--- blocks h10 @15');
for v in ('near_low_only','technical_reversal','sector_plus_technical','trigger_or_confirmed','momentum_continuation'):
    d=r['results'][v]; d=d if v=='momentum_continuation' else d['15.0']
    for b,s in d['blocks'].items(): row(f"{v[:16]} {b[:5]}", s['h10'])
print('--- higher cost, tech 15');
for h in ('h5','h10','h20'): row('higher '+h, r['results']['technical_reversal']['15.0']['all'][h]['higher'])
print('--- regime'); [row(k,s) for k,s in r['regime_split_technical_reversal_15_h10'].items()]
print('--- quadrant'); [row(k,s) for k,s in r['sector_quadrant_split_technical_reversal_15_h10'].items()]
