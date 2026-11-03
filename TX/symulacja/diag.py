import sys, collections
import sim2 as M
name = sys.argv[1]
fn = M.VARIANTS[name]
cause = collections.Counter(); ex = []
wrong_time = collections.Counter()
for seed in range(1, 301):
    w = M.World2(seed)
    acks, cycles, awake = fn(w, seed)
    for (ta, v, tm) in acks:
        tr = max(w.truth(tm), 25.0)
        if abs(v - tr) > M.BAD_ERR:
            rem = w.removal(tm)
            near_reset = any(0 <= tm - r < 14 for r in w.resets)
            near_pump = any(-6 <= tm - p*24 < 30 for p in w.pumps)
            c = ("removal:" + rem[2]) if rem else ("po resecie" if near_reset else ("wywoz" if near_pump else "normalny"))
            cause[c] += 1
            if len(ex) < 8 and not rem: ex.append((seed, round(tm,1), round(v,1), round(tr,1), c))
    # czas "wrong view" - rozbicie
    for h in range(2, int(w.H)):
        i = max([k for k,a in enumerate(acks) if a[0] <= h], default=None)
        if i is None: continue
        v = sorted(acks)[i] if False else None
print(name, dict(cause)); print(ex)
