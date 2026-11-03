import os, sys, random, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FAULTS", "1")
import swarm.d_konsensus as D
import sim2 as S2
rec = []
orig_cycle = D.DLogic.cycle
def cyc(self, sensor, clock, ref):
    v, st = orig_cycle(self, sensor, clock, ref)
    rec.append(dict(echo=getattr(sensor, "echo_on", False), v=v, st=st,
                    truth=S2.World2.truth(self._w, clock.s/3600), refv=ref["value"], refvalid=ref["valid"]))
    return v, st
D.DLogic.cycle = cyc
names = ["V4 firmware (+-1.5, min12)", "D1 prior min6"]
for nm in names:
    cfg = [c for c in D.VARIANTS_D if c["name"] == nm][0]
    rec.clear()
    stats = collections.Counter()
    for seed in range(1, 101):
        w = S2.World2(seed); w_ = w
        def run_one(w=w, seed=seed):
            lg = D.DLogic(cfg); lg._w = w
            return lg.run(w, seed)
        rec.clear()
        run_one()
        for r in rec:
            if r["v"] is None: 
                stats["none_echo" if r["echo"] else "none_clean"] += 1
                continue
            err = abs(r["v"] - r["truth"])
            key = ("echo" if r["echo"] else "clean") + ("_bad" if err > 8 else "_ok")
            stats[key] += 1
            if err > 8 and r["echo"]:
                stats["bad_refvalid_%s" % r["refvalid"]] += 1
    print(nm, dict(sorted(stats.items())))
