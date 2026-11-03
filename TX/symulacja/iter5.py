import sys
import sim2 as M
import sweep as W
from sim2 import V0, V1

V2 = dict(V1, name="V2", prior=True, persist=True, pool_half=1.5)
EXT = [1800, 1800, 1800, 3600, 3600, 7200, 7200]
V3 = dict(V2, name="V3", retry=EXT, remeasure=True)
NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", V0["name"], "V3"]
W.reg(V3)
NAMES.append(W.reg(dict(V3, name="V3 n_series=8", n_series=8, pool_min=16)))
NAMES.append(W.reg(dict(V3, name="V3 n=8 int 10s", n_series=8, pool_min=16, int_s=10)))

if __name__ == "__main__":
    res = M.run_all(NAMES, 300)
    W.show(res, NAMES)
