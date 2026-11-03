#!/usr/bin/env python3
"""
Symulacja 3: logika V3 (v1.7.0) i V4 (v1.7.1) + bledy czujnika znalezione w logu pomiary.txt (2026-10-08).

Dodatkowe bledy czujnika (poza scenariuszem sim2: 6 epizodow na 50 dni, bez nakladania sie i bez wywozow):
 - "echo"      : 12-36 h. ~55% probek stale 25.2-25.8 cm (falszywe echo tuz nad strefa martwa), ~35% timeout, ~10% prawda
                (cykl 3 z logu: poziom ok. 75 cm, falszywe echo ok. 25.4 cm)
 - "echo_long": 60-84 h. Jak "echo", ale dlugo - test, czy odniesienie nie zresetuje sie na falszywe echo
 - "blind"    : 12-48 h. Czujnik slepy: ~85% timeout/odrzut, ~15% odczytow 25.1 (cykle 11-12 z logu)
 - "dz"       : 12-48 h. Czujnik slepy z przewaga odczytow < 25 cm przy realnym poziomie 40-75 cm
                (test falszywej strefy martwej -> wysylka 25.0 cm)

Uruchomienie:  python sim3.py [liczba_przebiegow]      (FAULTS=0 wylacza nowe bledy - kontrola regresji)
"""
import math
import os
import random
import sys
from multiprocessing import Pool

import sim as S
import sim2 as M
from sim2 import NewLogic, MIN_VALID, SLEEP_S
import iter_final as F  # rejestruje V2 i V3 (v1.7.0)

FAULTS = os.environ.get("FAULTS", "1") != "0"
EP_TYPES = [("echo", 12, 36), ("echo", 12, 36), ("echo_long", 60, 84),
            ("blind", 12, 48), ("blind", 12, 48), ("dz", 12, 48)]


class World3(M.World2):
    def __init__(self, seed):
        super().__init__(seed)
        self.episodes = []
        if not FAULTS:
            return
        r = random.Random(seed * 31 + 7)
        busy = [(p * 24 - 30, p * 24 + 50) for p in self.pumps]
        for kind, lo, hi in EP_TYPES:
            for _ in range(200):
                s = r.uniform(3 * 24, 46 * 24)
                dur = r.uniform(lo, hi)
                if all(s + dur < a or s > b for a, b in busy):
                    busy.append((s - 12, s + dur + 12))
                    self.episodes.append((s, s + dur, kind))
                    break

    def episode(self, th):
        for e in self.episodes:
            if e[0] <= th < e[1]:
                return e[2]
        return None


class Sensor3(M.Sensor2):
    def measure(self):
        d = super().measure()
        ep = self.w.episode(self.c.h()) if hasattr(self.w, "episode") else None
        if ep is None:
            return d
        r = self.r
        u = r.random()
        truth = max(self.w.truth(self.c.h()), MIN_VALID)
        if ep in ("echo", "echo_long"):
            if u < 0.35:
                return -1.0
            if u < 0.90:
                return max(25.05, r.gauss(25.4, 0.2))
            return truth + r.gauss(0, 0.4)
        if ep == "blind":
            return max(25.05, r.gauss(25.1, 0.02)) if u < 0.15 else -1.0
        # "dz": glownie odczyty < 25 cm
        if u < 0.60:
            return r.uniform(18, 24.9)
        if u < 0.85:
            return -1.0
        return max(25.05, r.gauss(25.1, 0.02))


M.World2 = World3
M.Sensor2 = Sensor3


class NewLogic4(NewLogic):
    """Port poprawek v1.7.1: NEAR_MIN_MARGIN_CM i wiarygodnosc strefy martwej (DEADZONE_PLAUSIBLE_MARGIN_CM)."""

    def window(self, ref):
        days = (ref["cycles"] + 1) * (self.cfg.get("sleep_s", SLEEP_S) / 86400.0)
        return self.cfg["fill_day"] * days + self.cfg["noise"]

    def cycle(self, sensor, clock, ref):
        c = self.cfg
        sensor.begin_cycle(c["n_series"])
        st = dict(total=0, valid=0, below=0, above=0, timeouts=0)
        pool = []
        for s in range(c["n_series"]):
            self.series(sensor, clock, st, pool)
            if s < c["n_series"] - 1:
                clock.s += c["int_s"]
        val, _agree = self.cons_pool(pool, st, ref)
        if val is None:
            mostly_below = st["below"] * 100 >= 50 * st["total"]
            plausible = ref["valid"] and (ref["value"] - self.window(ref)) <= MIN_VALID + c["dz_plaus"]
            if mostly_below and plausible and ref["value"] <= c["dz_last"]:
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
        elif self.within(ref, val):
            self.accept(ref, val)
        else:
            if val < MIN_VALID + c["near_min"]:
                ref["dz"] = 0
                ref["cycles"] += 1
                return None, "NO_VALID"
            if ref["rej"] >= c["max_rej"]:
                self.accept(ref, val)
            else:
                ref["rej"] += 1
                ref["dz"] = 0
                ref["cycles"] += 1
                return None, "JUMP_REJECTED"
        return val, "OK"


V3 = F.V3
V4 = dict(V3, name="V4 (v1.7.1 poprawki)", near_min=5.0, dz_plaus=5.0)
M.register(V4["name"], lambda w, s: NewLogic4(V4).run(w, s))
NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", V3["name"], V4["name"]]


def one(args):
    name, seed = args
    w = World3(seed)
    acks, cycles, awake = M.VARIANTS[name](w, seed)
    m = M.metrics(acks, cycles, awake, w)
    # falszywy "pelny": dostarczone <= 30 cm, gdy realny poziom >= 40 cm
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
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    res = run(NAMES, runs)
    txt = M.table(res, NAMES)
    cols = [res[k] for k in NAMES]
    txt += "\n| Falszywe \"pelny\" (<= 30 cm przy poziomie >= 40) [szt./50 dni] | " + " | ".join(
        f"{r['falsefull']:.2f}" for r in cols) + " |"
    txt += "\n| Przebiegi z >= 1 falszywym \"pelny\" [%] | " + " | ".join(f"{r['ff_runs']:.0f}" for r in cols) + " |"
    print(f"FAULTS={int(FAULTS)}, przebiegow: {runs}\n")
    print(txt)
