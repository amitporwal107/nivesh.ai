import json, math, sys, csv
from statistics import mean, stdev
o = json.load(open('run.json'))
def stats(key, cost, side):
    ex, names, hits = [], 0, 0
    for d, day in o['days'].items():
        L = [x for x in day[key] if x['oc'] is not None]
        u = day[key.split('_')[0] + '_univ_oc']
        if not L or u is None: continue
        sgn = 1 if side == 'bull' else -1
        m = mean(x['oc'] for x in L) * sgn
        ex.append(m - u * sgn); names += len(L); hits += sum(1 for x in L if x['oc'] * sgn > 0)
    if not ex: return f"{key}: no days with names"
    sd = stdev(ex) if len(ex) > 1 else float('nan'); se = sd / math.sqrt(len(ex))
    m = mean(ex)
    return (f"{key}: days {len(ex)}, names {names}, hit {hits}/{names}, mean excess {m:+.2f} %/day "
            f"(sd {sd:.2f}, se {se:.2f}, t {m/se:+.2f}); after {cost} % cost {m-cost:+.2f}; 95% CI of excess "
            f"[{m-1.96*se:+.2f}, {m+1.96*se:+.2f}]")
print(stats('FNO_bull', 0.204, 'bull')); print(stats('FNO_bear', 0.204, 'bear')); print(stats('CASH_bull', 0.37, 'bull'))
mom = [(day['FNO_mom_oc'] - day['FNO_univ_oc']) for d, day in o['days'].items() if day['FNO_mom_oc'] is not None and day['FNO_univ_oc'] is not None]
print(f"FNO momentum-only (RS10 top 5) baseline: days {len(mom)}, mean excess {mean(mom):+.2f} %/day, sd {stdev(mom):.2f}")
