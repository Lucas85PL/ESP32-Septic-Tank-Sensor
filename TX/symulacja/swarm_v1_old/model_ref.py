#!/usr/bin/env python3
"""Wariant C - 'model odniesienia': adaptacyjne tempo napelniania, predykcja, bezpieczniejszy reset.

Uruchomienie (z katalogu symulacja/):  python swarm/model_ref.py [liczba_przebiegow]
Zalezy od sim2.py (swiat, czujnik, metryki). sim2.py NIE jest modyfikowany.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import sim2 as S2  # noqa: E402
from sim2 import NewLogic, Clock, Sensor2, Radio2, send_full, run_all, table, SLEEP_S, MIN_VALID  # noqa: E402

RATE_LO, RATE_HI = 0.5, 15.0  # tempo [cm/dobe], obciecie

BASE = dict(
    n_series=6, int_s=20, min_samples=5, cons="pool",
    pool_half=1.5, pool_min=12, pool_ratio=1.5, prior=True,       # = firmware V4 (measurement.cpp)
    fill_day=15.0, noise=5.0, empty_zone=140.0, max_rej=2,
    dz_cycles=3, dz_last=70.0,
    retry=[1800, 1800, 1800, 3600, 3600, 7200, 7200], remeasure=True,
    persist=True, sleep_s=SLEEP_S,
    # nowe opcje
    adaptive=False,       # okno = min(15/dobe, k*tempo*dni + m)
    nearest=False,        # wybor klastra najblizszego predykcji (zamiast najwiekszego w oknie)
    reset_confirm=False,  # reset po 2 odrzuceniach wymaga zgodnosci 2 kolejnych cykli
    rise_forget=False,    # po wywozie (skok w gore >5 cm) zapomnij tempo
    k=1.5, m=4.0, ema=0.3, confirm_tol=3.0,
)


class AdaptLogic(NewLogic):
    # ---- pomocnicze ----
    def days(self, ref):
        return (ref["cycles"] + 1) * (self.cfg["sleep_s"] / 86400.0)

    def rate_of(self, ref):
        if not self.cfg["adaptive"]:
            return None
        return ref.get("rate")

    # ---- okno walidacji z modelem tempa ----
    def within(self, ref, v):
        c = self.cfg
        d = self.days(ref)
        delta = v - ref["value"]
        if delta > c["noise"]:
            return v >= c["empty_zone"]           # wywoz: tylko wysoki wynik
        w = c["fill_day"] * d + c["noise"]        # okno sztywne (V4)
        r = self.rate_of(ref)
        if r is not None:
            w = min(w, c["k"] * r * d + c["m"])   # ciasniej, gdy tempo znane
        return delta >= -w

    # ---- akceptacja + uczenie tempa (EMA) ----
    def accept(self, ref, v, learn=True):
        c = self.cfg
        if learn and ref.get("valid") and abs(v - MIN_VALID) > 1e-6:
            d = self.days(ref)
            if v - ref["value"] > c["noise"]:          # wywoz / skok w gore
                if c["rise_forget"]:
                    ref["rate"] = None
            else:
                obs = min(RATE_HI, max(0.0, ref["value"] - v) / d)
                r = ref.get("rate")
                r = obs if r is None else r + c["ema"] * (obs - r)
                ref["rate"] = min(RATE_HI, max(RATE_LO, r))
        ref.update(value=v, valid=True, cycles=0, rej=0, dz=0, rpend=None)

    # ---- wybor klastra: najblizszy predykcji ----
    def cons_pool(self, pool, st, ref):
        c = self.cfg
        cl = [x for x in self.clusters(pool) if x[0] >= c["pool_min"]]
        if not cl:
            return None, 0
        if c["prior"] and ref["valid"]:
            ok = [x for x in cl if self.within(ref, x[1])]
            if ok:
                r = self.rate_of(ref)
                if c["nearest"] and r is not None:
                    pred = ref["value"] - r * self.days(ref)
                    best = min(ok, key=lambda x: abs(x[1] - pred))
                    return best[1], best[0]
                return ok[0][1], ok[0][0]
        top = cl[0]
        second = cl[1][0] if len(cl) > 1 else 0
        if top[0] >= c["pool_ratio"] * second:
            return top[1], top[0]
        return None, 0

    # ---- cykl (kopia V4 z poprawkami resetu) ----
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
            if st["below"] * 100 >= 50 * st["total"] and ref["valid"] and ref["value"] <= c["dz_last"]:
                ref["dz"] = min(ref["dz"] + 1, c["dz_cycles"])
                if ref["dz"] >= c["dz_cycles"]:
                    self.accept(ref, MIN_VALID, learn=False)
                    ref["dz"] = c["dz_cycles"]
                    return MIN_VALID, "DEADZONE"
                ref["cycles"] += 1
                return None, "NO_VALID"
            ref["dz"] = 0
            ref["cycles"] += 1
            return None, "NO_VALID"
        if not ref["valid"]:
            self.accept(ref, val, learn=False)
        elif self.within(ref, val):
            self.accept(ref, val)
        elif ref["rej"] >= c["max_rej"]:
            confirmed = ref.get("rpend") is not None and abs(val - ref["rpend"]) <= c["confirm_tol"]
            if c["reset_confirm"] and not confirmed:
                ref["rpend"] = val
                ref["dz"] = 0
                ref["cycles"] += 1
                return None, "JUMP_REJECTED"
            self.accept(ref, val, learn=False)   # reset odniesienia
        else:
            ref["rej"] += 1
            ref["rpend"] = val
            ref["dz"] = 0
            ref["cycles"] += 1
            return None, "JUMP_REJECTED"
        return val, "OK"


def _register(name, cfg):
    S2.register(name, (lambda cc: (lambda w, s: AdaptLogic(cc).run(w, s)))(cfg))


V4 = dict(BASE, name="V4 (firmware, port)")
C1 = dict(BASE, name="C1 tempo+predykcja", adaptive=True, nearest=True)
C2 = dict(C1, name="C2 +reset z potwierdzeniem", reset_confirm=True)
C3 = dict(C2, name="C3 +zapomnij tempo po wywozie", rise_forget=True)
CONFIGS = [V4, C1, C2, C3]

for _cfg in CONFIGS:
    _register(_cfg["name"], _cfg)

NAMES = [c["name"] for c in CONFIGS]

if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    results = run_all(NAMES, runs)
    print(table(results, NAMES))
