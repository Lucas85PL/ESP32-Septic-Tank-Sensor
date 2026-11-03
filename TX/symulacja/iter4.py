import sys
import sim2 as M
import sweep as W
from sim2 import V0, V1

V2 = dict(V1, name="V2", prior=True, persist=True, pool_half=1.5)
EXT = [1800, 1800, 1800, 3600, 3600, 7200, 7200]
V3 = dict(V2, name="V3 (V2+retry rozsz.+ponowny pomiar)", retry=EXT, remeasure=True)
NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", V0["name"], V2["name"], V3["name"]]
W.reg(V2); W.reg(V3)
for fd, nz in ((15, 5), (12, 4), (10, 4), (10, 3), (8, 3)):
    NAMES.append(W.reg(dict(V3, name=f"V3 okno {fd}cm/d + {nz}cm", fill_day=float(fd), noise=float(nz))))
NAMES.append(W.reg(dict(V3, name="V3 okno 10/4 max_rej=1", fill_day=10.0, noise=4.0, max_rej=1)))
NAMES.append(W.reg(dict(V3, name="V3 okno 10/4 max_rej=3", fill_day=10.0, noise=4.0, max_rej=3)))

if __name__ == "__main__":
    res = M.run_all(NAMES, int(sys.argv[1]) if len(sys.argv) > 1 else 300)
    W.show(res, NAMES)
