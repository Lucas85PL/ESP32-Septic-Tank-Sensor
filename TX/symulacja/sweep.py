import sys
import sim2 as M
from sim2 import V0, V1, NewLogic

def reg(cfg):
    M.register(cfg["name"], (lambda c: (lambda w, s: NewLogic(c).run(w, s)))(cfg))
    return cfg["name"]

def show(results, order):
    print(f"{'wariant':38s} {'dobry%':>7s} {'nieakt%':>8s} {'bledny%':>8s} {'MAE':>5s} {'bl.sz':>6s} {'gr.bl':>6s} {'dostaw':>7s} {'NOVAL':>6s} {'min/d':>6s}")
    for k in order:
        r = results[k]
        print(f"{k:38s} {r['good']:7.1f} {r['stale']:8.1f} {r['wrong']:8.1f} {r['mae']:5.1f} {r['wrong_n']:6.2f} {r['big_n']:6.2f} {r['deliv']:7.1f} {r['sts']['NO_VALID']:6.1f} {r['awake']:6.1f}")
