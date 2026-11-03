import sys
import sim2 as M
name, mode = sys.argv[1], sys.argv[2]
shown = 0
for seed in range(1, 301):
    w = M.World2(seed)
    acks, cycles, awake = M.VARIANTS[name](w, seed)
    bad = [a for a in acks if abs(a[1]-max(w.truth(a[2]),25))>M.BAD_ERR and (w.removal(a[2]) or [0,0,''])[2]==mode]
    if bad and shown < 3:
        shown += 1
        r = [x for x in w.removals if x[2]==mode][0]
        print(f"seed {seed} removal {r[0]:.1f}-{r[1]:.1f} h, pumps(h) {[round(p*24,1) for p in w.pumps]}, resets {[round(x,1) for x in w.resets]}, outages {[(round(a,1),round(b,1)) for a,b in w.outages]}")
        for c in cycles:
            if r[0]-30 <= c['t'] <= r[1]+14:
                print(f"   t={c['t']:7.1f} truth={w.truth(c['t']):6.1f} status={c['status']:14s} value={c['value']} sent={c['sent']}")
