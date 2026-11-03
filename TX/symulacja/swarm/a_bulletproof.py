#!/usr/bin/env python3
"""
Zadanie A: wariant 'bulletproof' (A) = V4 + cztery zabezpieczenia.

 (1) wolne okno napelniania dla kandydatow tuz nad minimum (< 25 + NEAR_ZONE_CM): SLOW_RATE_CM_DAY zamiast 15
 (2) detektor stalej wartosci: waski (sd <= ECHO_SD_CM), powtarzalny w >= ECHO_NSER seriach klaster < 30 cm
     przy wysokim odsetku timeoutow (>= ECHO_TO_RATIO) -> echo, klaster ignorowany (bez resetu odniesienia)
 (3) skok w dol > DROP_CM w jednym cyklu wymaga potwierdzenia w nastepnym cyklu (+-DROP_TOL_CM)
 (4) strefa martwa wymaga rozrzutu probek < 25 cm (sd >= DZ_SD_MIN_CM); stabilne echo ~18 cm nie wysyla 25.0

Uruchomienie:  FAULTS=1 python a_bulletproof.py 150
               FAULTS=0 python a_bulletproof.py 150
               AEXTRA=1 FAULTS=1 python a_bulletproof.py 150   (dodatkowy scenariusz: stabilne echo 18 cm)
"""
import bisect
import os
import random
import statistics
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
SYM = os.path.dirname(HERE)
sys.path.insert(0, SYM)

import sim as S  # noqa: E402
import sim2 as M  # noqa: E402
import sim3 as S3  # noqa: E402
from sim2 import MIN_VALID, SLEEP_S  # noqa: E402

AEXTRA = os.environ.get("AEXTRA", "0") != "0"

# ---------------- parametry wariantu A ----------------
A_BASE = dict(S3.V4, name="A bulletproof")
A_BASE.update(
    slow_rate=float(os.environ.get("A_SLOW", 8.0)), near_zone=10.0,      # (1) kandydat < 35 cm: 8 cm/dobe
    dz_rate=8.0,                        # plausibility strefy martwej liczona tez 8 cm/dobe
    drop_cm=10.0, drop_tol=float(os.environ.get("A_DROP_TOL", 6.0)),         # (3)
    echo_zone=5.0, echo_sd=0.3, echo_nser=4, echo_to=0.2,  # (2)
    dz_sd_min=1.5,                      # (4)
    drop_guard=True, echo_guard=True, dz_sd_guard=True,
)


# ---------------- swiat z dodatkowym scenariuszem (opcjonalnie) ----------------
class World4(S3.World3):
    def __init__(self, seed):
        super(S3.World3, self).__init__(seed)  # World2
        self.episodes = []
        if not S3.FAULTS:
            return
        r = random.Random(seed * 31 + 7)
        busy = [(p * 24 - 30, p * 24 + 50) for p in self.pumps]
        ep_types = S3.EP_TYPES + [("echo18", 12, 36), ("echo18", 12, 36)]
        for kind, lo, hi in ep_types:
            for _ in range(200):
                s = r.uniform(3 * 24, 46 * 24)
                dur = r.uniform(lo, hi)
                if all(s + dur < a or s > b for a, b in busy):
                    busy.append((s - 12, s + dur + 12))
                    self.episodes.append((s, s + dur, kind))
                    break


class Sensor4(S3.Sensor3):
    """Stabilne echo ~18 cm: 60% probek 18.0 +- 0.2, 30% timeout, 10% prawda."""

    def measure(self):
        ep = self.w.episode(self.c.h()) if hasattr(self.w, "episode") else None
        if ep != "echo18":
            return super().measure()
        super(S3.Sensor3, self).measure()  # Sensor2.measure: krok czasu i serie
        u = self.r.random()
        if u < 0.30:
            return -1.0
        if u < 0.90:
            return self.r.gauss(18.0, 0.2)
        return self.w.truth(self.c.h()) + self.r.gauss(0, 0.4)


if AEXTRA:
    M.Sensor2 = Sensor4


# ---------------- logika A ----------------
class ALogic(S3.NewLogic4):
    def accept(self, ref, v):
        ref.update(value=v, valid=True, cycles=0, rej=0, dz=0)
        ref["pend"] = None

    def rate_for(self, v):
        c = self.cfg
        return c["slow_rate"] if v < MIN_VALID + c["near_zone"] else c["fill_day"]

    def within(self, ref, v):
        c = self.cfg
        days = (ref["cycles"] + 1) * (c.get("sleep_s", SLEEP_S) / 86400.0)
        window = self.rate_for(v) * days + c["noise"]
        delta = v - ref["value"]
        if delta > c["noise"]:
            return v >= c["empty_zone"]
        return delta >= -window

    def window(self, ref):
        c = self.cfg
        days = (ref["cycles"] + 1) * (c.get("sleep_s", SLEEP_S) / 86400.0)
        return c["dz_rate"] * days + c["noise"]

    def series_t(self, sensor, clock, st, vals, tags, below, s):
        for i in range(S.SAMPLES):
            d = sensor.measure()
            st["total"] += 1
            if d < 0:
                st["timeouts"] += 1
            elif d < MIN_VALID:
                st["below"] += 1
                below.append(d)
            elif d > M.MAX_VALID:
                st["above"] += 1
            else:
                st["valid"] += 1
                vals.append(d)
                tags.append(s)
            if i < S.SAMPLES - 1:
                clock.s += 1.0

    def clusters_t(self, vals, tags):
        """Zachlanne okna (szer. 2*pool_half) z zachowaniem numeru serii; do 3 klastrow."""
        w = 2 * self.cfg["pool_half"]
        remaining = sorted(range(len(vals)), key=lambda i: vals[i])
        out = []
        for _ in range(3):
            if not remaining:
                break
            sv = [vals[i] for i in remaining]
            best_i, best_n = 0, 0
            for i in range(len(sv)):
                j = bisect.bisect_right(sv, sv[i] + w)
                if j - i > best_n:
                    best_i, best_n = i, j - i
            members = remaining[best_i:best_i + best_n]
            vs = [vals[i] for i in members]
            out.append(dict(n=len(members), med=S.median(vs),
                            sd=statistics.pstdev(vs) if len(vs) > 1 else 0.0,
                            nser=len(set(tags[i] for i in members))))
            remaining = remaining[:best_i] + remaining[best_i + best_n:]
        return out

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
        if c["echo_guard"]:  # (2) stale echo near the floor
            cls = [k for k in cls if not (
                k["med"] < MIN_VALID + c["echo_zone"] and k["sd"] <= c["echo_sd"]
                and k["nser"] >= c["echo_nser"] and to_ratio >= c["echo_to"])]
        cands = [k for k in cls if k["n"] >= c["pool_min"]]

        val = None
        if cands:
            if ref["valid"]:
                ok = [k for k in cands if self.within(ref, k["med"])]
                if ok:
                    val = ok[0]["med"]
            if val is None:
                second = cands[1]["n"] if len(cands) > 1 else 0
                if cands[0]["n"] >= c["pool_ratio"] * second:
                    val = cands[0]["med"]

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
            self.accept(ref, val)
            return val, "OK"

        if c["drop_guard"] and val < MIN_VALID + c["near_zone"] and val - ref["value"] < -c["drop_cm"]:  # (3)
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


# ---------------- warianty do porownania ----------------
A = A_BASE
VARIANTS_CFG = {
    A["name"]: A,
    "A bez (3) skok w dol": dict(A, name="A bez (3) skok w dol", drop_guard=False),
    "A bez (2) echo": dict(A, name="A bez (2) echo", echo_guard=False),
    "A bez (4) rozrzut dz": dict(A, name="A bez (4) rozrzut dz", dz_sd_guard=False),
    "A bez (1) wolne okno": dict(A, name="A bez (1) wolne okno", slow_rate=15.0),
}
for _name, _cfg in VARIANTS_CFG.items():
    M.register(_name, (lambda cfg: (lambda w, s: ALogic(cfg).run(w, s)))(_cfg))

NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", S3.V3["name"], S3.V4["name"], A["name"]]
ABL = ["A bez (3) skok w dol", "A bez (2) echo", "A bez (4) rozrzut dz", "A bez (1) wolne okno"]


def one(args):
    name, seed = args
    w = World4(seed) if AEXTRA else S3.World3(seed)
    acks, cycles, awake = M.VARIANTS[name](w, seed)
    m = M.metrics(acks, cycles, awake, w)
    m["falsefull"] = sum(1 for a in acks if a[1] <= 30.0 and w.truth(a[2]) >= 40.0)
    m["falsedz"] = sum(1 for a in acks if abs(a[1] - MIN_VALID) < 1e-6 and w.truth(a[2]) >= 40.0)
    return name, m


def run(names, runs):
    jobs = [(nm, seed) for nm in names for seed in range(1, runs + 1)]
    with Pool() as p:
        res = p.map(one, jobs, chunksize=8)
    by = {}
    for nm, m in res:
        by.setdefault(nm, []).append(m)
    out = {}
    for nm, ms in by.items():
        s = M.summarize(ms)
        s["falsefull"] = sum(m["falsefull"] for m in ms) / len(ms)
        s["ff_runs"] = 100 * sum(1 for m in ms if m["falsefull"] > 0) / len(ms)
        s["falsedz"] = sum(m["falsedz"] for m in ms) / len(ms)
        s["fd_runs"] = 100 * sum(1 for m in ms if m["falsedz"] > 0) / len(ms)
        out[nm] = s
    return out


def extra_rows(res, names):
    cols = [res[k] for k in names]
    rows = [
        ("Falszywe \"pelny\" (<= 30 cm przy poziomie >= 40) [szt./50 dni]", lambda r: f"{r['falsefull']:.2f}"),
        ("Przebiegi z >= 1 falszywym \"pelny\" [%]", lambda r: f"{r['ff_runs']:.0f}"),
        ("Falszywe 25.0 w strefie martwej (poziom >= 40) [szt./50 dni]", lambda r: f"{r['falsedz']:.2f}"),
        ("Przebiegi z >= 1 falszywym 25.0 [%]", lambda r: f"{r['fd_runs']:.0f}"),
    ]
    return "\n".join(f"| {lab} | " + " | ".join(fn(r) for r in cols) + " |" for lab, fn in rows)


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    names = NAMES + ABL
    res = run(names, runs)
    head = f"FAULTS={int(S3.FAULTS)}, AEXTRA={int(AEXTRA)}, przebiegow: {runs}\n"
    print(head)
    print(M.table(res, names))
    print(extra_rows(res, names))
