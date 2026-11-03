import sim2 as M
import sweep as W
from sim2 import V0, V1

V2 = dict(V1, name="V2 (klastry+prior+persist)", prior=True, persist=True, pool_half=1.5)
EXT = [1800, 1800, 1800, 3600, 3600, 7200, 7200]
NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", V0["name"], V1["name"]]
NAMES.append(W.reg(V2))
for n in (3, 4, 8):
    NAMES.append(W.reg(dict(V2, name=f"V2 n_series={n}", n_series=n, pool_min=2 * n)))
NAMES.append(W.reg(dict(V2, name="V2 sen 6h", sleep_s=21600)))
NAMES.append(W.reg(dict(V2, name="V2 sen 6h n=4", sleep_s=21600, n_series=4, pool_min=8)))
NAMES.append(W.reg(dict(V2, name="V2 sen 8h n=4", sleep_s=28800, n_series=4, pool_min=8)))
NAMES.append(W.reg(dict(V2, name="V2 retry rozszerzony", retry=EXT)))
NAMES.append(W.reg(dict(V2, name="V2 retry rozsz.+ponowny pomiar", retry=EXT, remeasure=True)))
NAMES.append(W.reg(dict(V2, name="V2 n=4 retry rozsz.+ponowny pom.", n_series=4, pool_min=8, retry=EXT, remeasure=True)))

if __name__ == "__main__":
    res = M.run_all(NAMES, 300)
    W.show(res, NAMES)
    print()
    for k in NAMES[4:]:
        r = res[k]
        print(f"{k:38s} wywoz {r['pump'][0]:5.1f}/{r['pump'][1]:5.1f}h  reset {r['reset'][0]:5.1f}/{r['reset'][1]:5.1f}h  awaria RX {r['outage'][0]:5.1f}/{r['outage'][1]:5.1f}h")
