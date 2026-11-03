import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import c_bulletproof as C
from multiprocessing import Pool
if __name__ == "__main__":
    pass
if True:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    variants = {
        "C-B bez R4 (K=999)": dict(C.CFG_B, name="C-B bez R4", K=999),
        "C-B R4 bez 'bad' (bad_expire=0)": dict(C.CFG_B, name="C-B R4 bez bad", bad_expire=0),
        "C-B cand_tol=3": dict(C.CFG_B, name="C-B cand3", cand_tol=3.0),
    }
    for nm, cfg in variants.items():
        C.M.register(nm, (lambda cf: (lambda w, s: C.C(cf).run(w, s)))(cfg))
    names = [C.NAMES[3]] + list(variants) + [C.CFG_B["name"]]
    by = {}
    for nm in names:
        ms = []
        for seed in range(1, runs + 1):
            w = C.M.World2(seed)
            acks, cyc, aw = C.M.VARIANTS[nm](w, seed)
            m = C.M.metrics(acks, cyc, aw, w)
            m["falsefull"] = sum(1 for a in acks if a[1] <= 30.0 and w.truth(a[2]) >= 40.0)
            ms.append(m)
        s = C.M.summarize(ms)
        s["falsefull"] = sum(m["falsefull"] for m in ms) / len(ms)
        s["ff_runs"] = 100 * sum(1 for m in ms if m["falsefull"] > 0) / len(ms)
        by[nm] = s
    res = by
    txt = C.M.table(res, names)
    print(f"ABLACJA STRESS={int(C.STRESS)} FAULTS={int(C.T.FAULTS)} runs={runs}\n")
    print(txt)
