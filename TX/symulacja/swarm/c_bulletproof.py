#!/usr/bin/env python3
"""
Zadanie C: wyjscie z falszywego odniesienia ("bulletproof").

Warianty:
  C-A : V4 + R1 (kandydat: wzrost/spadek poza oknem akceptowany po 2 kolejnych zgodnych cyklach,
        zawsze) + R2 (bootstrap: 2 zgodne cykle albo klaster wiarygodny >= 2*POOL_MIN)
        + R3 (czesciowy wywoz = R1 bez progu 140 cm) + R4 (bezpiecznik: K=4 cykle prawie stalej
        wartosci -> uniewaznienie odniesienia, wykluczenie tej wartosci przez 8 cykli).
  C-B : jak C-A, ale wzrost >= 140 cm akceptowany od razu (jak V4) - kompromis czasu wykrycia wywozu.

Scenariusze:
  STRESS=0 : swiat sim3 (World3: bledy z logu, FAULTS wg env, jak sim3.py)
  STRESS=1 : World4 = World3 + falszywe "zamrozenie" (stala falszywa wartosc 3-5 cykli, 55% probek;
             "frozen_long" 4-7 dni, 75% probek), reset TX w trakcie zamrozenia (flash z falszywa wartoscia),
             czesciowy wywoz (skok +50..60 cm, np. 70 -> 128) w losowym dniu 6-44.

Uruchomienie (z katalogu symulacja):
  python swarm\\c_bulletproof.py 150            # swiat sim3, FAULTS=1
  set FAULTS=0 && python swarm\\c_bulletproof.py 150
  set STRESS=1 && python swarm\\c_bulletproof.py 150
"""
import os
import random
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # katalog symulacja/

import sim2 as M  # noqa: E402
import sim3 as T  # noqa: E402  (rejestruje V4 i swiat World3)
from sim2 import MIN_VALID, SLEEP_S  # noqa: E402
from sim3 import World3, Sensor3, NewLogic4, V4  # noqa: E402

STRESS = os.environ.get("STRESS", "0") != "0"
_ORIG_SENSOR2 = M.Sensor2  # oryginalny Sensor2 (przed podmiana na Sensor4)


# ======================= LOGIKA C =======================
class C(NewLogic4):
    def _ensure(self, ref):
        ref.setdefault("cand", None)
        ref.setdefault("cand_n", 0)
        ref.setdefault("hist", [])
        ref.setdefault("bad", None)
        ref.setdefault("bad_age", 0)

    def inwin(self, ref, v):
        d = v - ref["value"]
        return -self.window(ref) <= d <= self.cfg["noise"]

    def _accept(self, ref, v):
        c = self.cfg
        self.accept(ref, v)
        ref["cand"], ref["cand_n"] = None, 0
        h = ref["hist"]
        h.append(v)
        del h[:-c["K"]]
        # R4: bezpiecznik - K cykli prawie stalej wartosci -> wymus ponowna ocene
        if len(h) >= c["K"] and max(h) - min(h) <= c["stuck_tol"] and v > MIN_VALID + c["near_min"]:
            ref.update(bad=v, bad_age=c["bad_expire"], valid=False, hist=[], cand=None, cand_n=0)
            return None, "JUMP_REJECTED"
        return v, "OK"

    def _candidate(self, v, ref, fast=False):
        c = self.cfg
        if fast:
            ref["cand_n"] = c["confirm"]
        elif ref["cand"] is not None and abs(v - ref["cand"]) <= c["cand_tol"]:
            ref["cand_n"] += 1
        else:
            ref["cand"], ref["cand_n"] = v, 1
        if ref["cand_n"] >= c["confirm"]:  # R1/R3: potwierdzony skok
            return self._accept(ref, v)
        ref["cand"] = v
        ref["dz"] = 0
        ref["cycles"] += 1
        ref["rej"] += 1
        return None, "JUMP_REJECTED"

    def _no_cluster(self, st, ref):
        c = self.cfg
        ref["cand"], ref["cand_n"] = None, 0
        mostly_below = st["below"] * 100 >= 50 * st["total"]
        plausible = ref["valid"] and (ref["value"] - self.window(ref)) <= MIN_VALID + c["dz_plaus"]
        if mostly_below and plausible and ref["value"] <= c["dz_last"]:
            ref["dz"] = min(ref["dz"] + 1, c["dz_cycles"])
            if ref["dz"] >= c["dz_cycles"]:
                self.accept(ref, MIN_VALID)
                ref["dz"] = c["dz_cycles"]
                return MIN_VALID, "DEADZONE"
        else:
            ref["dz"] = 0
        ref["cycles"] += 1
        return None, "NO_VALID"

    def cycle(self, sensor, clock, ref):
        c = self.cfg
        self._ensure(ref)
        if ref["bad_age"] > 0:
            ref["bad_age"] -= 1
            if ref["bad_age"] == 0:
                ref["bad"] = None
        sensor.begin_cycle(c["n_series"])
        st = dict(total=0, valid=0, below=0, above=0, timeouts=0)
        pool = []
        for s in range(c["n_series"]):
            self.series(sensor, clock, st, pool)
            if s < c["n_series"] - 1:
                clock.s += c["int_s"]
        cls = [x for x in self.clusters(pool) if x[0] >= c["pool_min"]]
        if ref["bad"] is not None:
            cls = [x for x in cls if abs(x[1] - ref["bad"]) > c["bad_tol"]]
        if not cls:
            return self._no_cluster(st, ref)
        if ref["valid"]:
            inw = [x for x in cls if self.inwin(ref, x[1])]
            if inw:  # prior: najwiekszy klaster zgodny z oknem
                return self._accept(ref, max(inw)[1])
        top = max(cls)
        second = sorted(cls)[-2][0] if len(cls) > 1 else 0
        if top[0] < c["pool_ratio"] * second:  # brak dominacji -> jak V4
            return self._no_cluster(st, ref)
        if top[1] < MIN_VALID + c["near_min"]:  # strazak NEAR_MIN: 25-30 cm poza oknem = echo strefy martwej
            ref.update(cand=None, cand_n=0, dz=0)
            ref["cycles"] += 1
            return None, "NO_VALID"
        if not ref["valid"]:  # R2: bootstrap
            if top[0] >= c["strong_mult"] * c["pool_min"]:
                return self._accept(ref, top[1])
            return self._candidate(top[1], ref)
        fast = c["fast_empty"] and top[1] >= c["empty_zone"]
        return self._candidate(top[1], ref, fast=fast)


CFG_A = dict(
    V4, name="C-A (R1-R4)", K=4, stuck_tol=1.0, bad_tol=2.0, bad_expire=8, confirm=2, cand_tol=7.0,
    strong_mult=2, fast_empty=False,
)
CFG_B = dict(CFG_A, name="C-B (R1-R4 + >=140 od razu)", fast_empty=True)
M.register(CFG_A["name"], lambda w, s: C(CFG_A).run(w, s))
M.register(CFG_B["name"], lambda w, s: C(CFG_B).run(w, s))


# ======================= SWIAT STRESS (World4) =======================
class World4(World3):
    def __init__(self, seed):
        super().__init__(seed)
        r = random.Random(seed * 97 + 5)
        busy = [(p * 24 - 40, p * 24 + 60) for p in self.pumps]
        self.frozen = []
        for kind, lo, hi in [("frozen", 36, 60), ("frozen", 36, 60), ("frozen_long", 96, 168)]:
            for _ in range(300):
                s = r.uniform(3 * 24, 44 * 24)
                dur = r.uniform(lo, hi)
                if all(s + dur < a or s > b for a, b in busy):
                    busy.append((s - 12, s + dur + 12))
                    self.frozen.append((s, s + dur, kind, r.uniform(30, 150)))
                    break
        # reset TX w trakcie pierwszego zamrozenia (flash z falszywa wartoscia)
        if self.frozen:
            self.resets = sorted([self.frozen[0][0] + r.uniform(2, 8), self.resets[1]])
        # czesciowy wywoz: skok odleglosci +50..60 cm od losowej chwili (70 -> 128 typowo)
        while True:
            tp = r.uniform(6 * 24, 44 * 24)
            if all(abs(tp - p * 24) > 72 for p in self.pumps):
                break
        self.partial_t = tp
        self.partial_j = r.uniform(50, 60)
        self.pumps = list(self.pumps) + [tp / 24.0]  # do metryk "wykrycie wywozu"

    def truth(self, th):
        base = super().truth(th)
        if th >= self.partial_t:
            base = min(base + self.partial_j, 165.0)
        return base

    def frozen_at(self, th):
        for e in self.frozen:
            if e[0] <= th < e[1]:
                return e
        return None


class Sensor4(Sensor3):
    def measure(self):
        if not isinstance(self.w, World4):
            return super().measure()
        e = self.w.frozen_at(self.c.h())
        if e is None:
            return super().measure()
        _ORIG_SENSOR2.measure(self)  # obsluga serii i zegara jak w sim2
        r = self.r
        u = r.random()
        truth = max(self.w.truth(self.c.h()), MIN_VALID)
        p_stable = 0.55 if e[2] == "frozen" else 0.75
        if u < p_stable:
            return e[3] + r.gauss(0, 0.3)
        if u < p_stable + 0.15:
            return -1.0
        return truth + r.gauss(0, 0.4)


M.World2 = World4 if STRESS else World3
M.Sensor2 = Sensor4 if STRESS else Sensor3


# ======================= URUCHOMIENIE =======================
NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", "V3 (rekomendowana)", V4["name"],
         CFG_A["name"], CFG_B["name"]]


def one(args):
    name, seed = args
    w = M.World2(seed)
    acks, cycles, awake = M.VARIANTS[name](w, seed)
    m = M.metrics(acks, cycles, awake, w)
    m["falsefull"] = sum(1 for a in acks if a[1] <= 30.0 and w.truth(a[2]) >= 40.0)
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
        out[nm] = s
    return out


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    res = run(NAMES, runs)
    txt = M.table(res, NAMES)
    cols = [res[k] for k in NAMES]
    txt += "\n| Falszywe \"pelny\" (<= 30 cm przy poziomie >= 40) [szt./50 dni] | " + " | ".join(
        f"{r['falsefull']:.2f}" for r in cols) + " |"
    txt += "\n| Przebiegi z >= 1 falszywym \"pelny\" [%] | " + " | ".join(f"{r['ff_runs']:.0f}" for r in cols) + " |"
    head = f"STRESS={int(STRESS)} FAULTS={int(T.FAULTS)}, przebiegow: {runs}\n"
    print(head)
    print(txt)
