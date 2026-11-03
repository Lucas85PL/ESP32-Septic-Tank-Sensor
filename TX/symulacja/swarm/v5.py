#!/usr/bin/env python3
"""
V5 = V4 + reguly z roju: A (wolne okno <35 cm, rozrzut w strefie martwej, strozsze echo, skok w dol)
+ D1 (klaster zgodny z oczekiwaniem: >= prior_min probek i >= sup_prior serii) + opcjonalnie boot2
(bootstrap wymaga 2 zgodnych cykli).

Uruchomienie (z katalogu swarm):  FAULTS=1 python v5.py 150     |  python v5.py stress 120
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import a_bulletproof as AB  # noqa: E402
import sim2 as M  # noqa: E402
import sim3 as S3  # noqa: E402
from sim2 import MIN_VALID  # noqa: E402
import statistics  # noqa: E402


class V5Logic(AB.ALogic):
    def cycle(self, sensor, clock, ref):
        c = self.cfg
        sensor.begin_cycle(c["n_series"])
        st = dict(total=0, valid=0, below=0, above=0, timeouts=0)
        vals, tags, below = [], [], []
        for s in range(c["n_series"]):
            self.series_t(sensor, clock, st, vals, tags, below, s)
            if s < c["n_series"] - 1:
                clock.s += c["int_s"]

        to_ratio = st["timeouts"] / max(1, st["total"])
        cls = self.clusters_t(vals, tags)
        if c["echo_guard"]:
            cls = [k for k in cls if not (
                k["med"] < MIN_VALID + c["echo_zone"] and k["sd"] <= c["echo_sd"]
                and k["nser"] >= c["echo_nser"] and to_ratio >= c["echo_to"])]

        val = None
        if ref["valid"]:  # D1: klaster zgodny z oczekiwaniem - nizszy prog, ale wsparcie z wielu serii
            ok = [k for k in cls if k["n"] >= c["prior_min"] and k["nser"] >= c["sup_prior"]
                  and self.within(ref, k["med"])]
            if ok:
                val = ok[0]["med"]
        if val is None:
            dom = [k for k in cls if k["n"] >= c["pool_min"] and k["nser"] >= c["sup_dom"]]
            if dom:
                second = dom[1]["n"] if len(dom) > 1 else 0
                if dom[0]["n"] >= c["pool_ratio"] * second:
                    val = dom[0]["med"]

        if val is None:
            mostly_below = st["below"] * 100 >= 50 * st["total"]
            below_sd = statistics.pstdev(below) if len(below) > 1 else 0.0
            spread_ok = (not c["dz_sd_guard"]) or below_sd >= c["dz_sd_min"]
            plausible = ref["valid"] and (ref["value"] - self.window(ref)) <= MIN_VALID + c["dz_plaus"]
            if mostly_below and spread_ok and plausible and ref["value"] <= c["dz_last"]:
                ref["dz"] = min(ref["dz"] + 1, c["dz_cycles"])
                if ref["dz"] >= c["dz_cycles"]:
                    self.accept(ref, MIN_VALID)
                    ref["dz"] = c["dz_cycles"]
                    return MIN_VALID, "DEADZONE"
                ref["cycles"] += 1
                return None, "NO_VALID"
            ref["dz"] = 0
            ref["cycles"] += 1
            return None, "NO_VALID"

        if not ref["valid"]:
            if c.get("boot2"):
                b = ref.get("bpend")
                if b is None or abs(val - b) > c["boot_tol"]:
                    ref["bpend"] = val
                    return None, "NO_VALID"
            self.accept(ref, val)
            ref["bpend"] = None
            return val, "OK"

        if c["drop_guard"] and val < MIN_VALID + c["near_zone"] and val - ref["value"] < -c["drop_cm"]:
            p = ref.get("pend")
            if p is None or abs(val - p) > c["drop_tol"]:
                ref["pend"] = val
                ref["dz"] = 0
                ref["cycles"] += 1
                return None, "DROP_PENDING"

        if self.within(ref, val):
            self.accept(ref, val)
            return val, "OK"
        if val < MIN_VALID + c["near_min"]:
            ref["dz"] = 0
            ref["cycles"] += 1
            return None, "NO_VALID"
        if ref["rej"] >= c["max_rej"]:
            self.accept(ref, val)
            return val, "OK"
        ref["rej"] += 1
        ref["dz"] = 0
        ref["cycles"] += 1
        return None, "JUMP_REJECTED"


BASE = dict(AB.A_BASE, prior_min=6, sup_prior=3, sup_dom=1, boot2=False, boot_tol=3.0)
CFGS = [
    dict(BASE, name="V5a (A+D1)"),
    dict(BASE, name="V5b (A+D1+boot2)", boot2=True),
    dict(BASE, name="V5c (D1+rozrzut dz, bez echo/drop)", echo_guard=False, drop_guard=False),
    dict(BASE, name="V5d (A+D1, bez skoku w dol)", drop_guard=False),
]
for _c in CFGS:
    M.register(_c["name"], (lambda cfg: (lambda w, s: V5Logic(cfg).run(w, s)))(_c))
NAMES5 = [c["name"] for c in CFGS]

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stress":
        import e_stress as E
        runs = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        names = [S3.V3["name"], S3.V4["name"]] + NAMES5
        E.report(names, runs, out_name="v5_stress_wyniki.md")
    else:
        runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
        names = ["SUFIT (idealny czujnik)", S3.V3["name"], S3.V4["name"]] + NAMES5
        res = AB.run(names, runs)
        print(f"FAULTS={int(S3.FAULTS)}, przebiegow: {runs}\n")
        print(M.table(res, names))
        print(AB.extra_rows(res, names))
