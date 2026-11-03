#!/usr/bin/env python3
"""
Wariant D - konsensus i klastry (swarm).

UWAGA: sim3.py / wyniki3.md / NewLogic4 nie istnieja w projekcie. Baza to sim2.py (World2, Sensor2,
NewLogic, metryki). V4 (firmware) odtworzone 1:1 z src/measurement.cpp i src/config.h:
  okno klastra +-1.5 cm (szerokosc 3 cm), min 12 probek, do 3 klastrow, zgodnosc z oknem
  czasowym (prior), w przeciwnym razie dominacja 1.5x.

Model bledu 'echo' (wg opisu z logu): w cyklu z echem (prawdopodobienstwo ECHO_P) ~90% poprawnych
probek zwraca falszywe echo (25.4 cm lub stale dlugie echo 100-165 cm), prawda zostaje w ~10% probek.

FAULTS=0 : tylko bledy bazowe sim2 (bez echa)
FAULTS=1 : bledy bazowe sim2 + echo

Uruchomienie (z katalogu symulacja):  python swarm\\d_konsensus.py [runs]   (domyslnie 150)
"""
import bisect
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sim2 as S2  # noqa: E402

FAULTS = int(os.environ.get("FAULTS", "1"))
ECHO_P = float(os.environ.get("ECHO_P", "0.20"))   # prawdopodobienstwo cyklu z echem
ECHO_KEEP = 0.10                                    # ulamek probek, ktore zostaja prawdziwe

_med = S2.med


class SensorE(S2.Sensor2):
    """Sensor2 + model echa (aktywny tylko gdy FAULTS=1)."""

    def begin_cycle(self, n_series):
        super().begin_cycle(n_series)
        self.echo_on = FAULTS == 1 and self.r.random() < ECHO_P
        if self.echo_on:
            if self.r.random() < 0.5:
                self.echo_val, self.echo_sd = 25.4 + self.r.uniform(-0.2, 0.2), 0.15
            else:
                self.echo_val, self.echo_sd = self.r.uniform(100, 165), 0.3

    def measure(self):
        d = super().measure()
        if self.echo_on and S2.MIN_VALID <= d <= S2.MAX_VALID and self.r.random() >= ECHO_KEEP:
            return self.echo_val + self.r.gauss(0, self.echo_sd)
        return d


S2.Sensor2 = SensorE  # NewLogic.run korzysta z nazwy Sensor2 z modulu S2


class DLogic(S2.NewLogic):
    """Logika V4 z parametrami selekcji klastra. Probki w puli: (wartosc, numer_serii)."""

    def cycle(self, sensor, clock, ref):
        self._sid = 0
        return super().cycle(sensor, clock, ref)

    def series(self, sensor, clock, st, collect):
        tmp = []
        m = super().series(sensor, clock, st, tmp)
        collect.extend((v, self._sid) for v in tmp)
        self._sid += 1
        return m

    def _clusters(self, pool):
        c = self.cfg
        w = 2.0 * c.get("half", 1.5)
        s = sorted(pool)
        out = []
        for _ in range(3):
            if not s:
                break
            vals = [x[0] for x in s]
            best_i, best_n = 0, 0
            for i in range(len(s)):
                j = bisect.bisect_right(vals, vals[i] + w)
                if j - i > best_n:
                    best_i, best_n = i, j - i
            cl = s[best_i:best_i + best_n]
            vs = [x[0] for x in cl]
            mu = sum(vs) / len(vs)
            sd = (sum((x - mu) ** 2 for x in vs) / len(vs)) ** 0.5
            out.append(dict(n=best_n, med=_med(vs), sids=len({x[1] for x in cl}), sd=sd))
            s = s[:best_i] + s[best_i + best_n:]
        return out

    def cons_pool(self, pool, st, ref):
        c = self.cfg
        cls = self._clusters(pool)
        mode = c.get("mode", "count")

        def score(cl):
            return cl["n"] if mode == "count" else cl["n"] * cl["sids"]

        def ok(cl, min_n, sup):
            return cl["n"] >= min_n and cl["sids"] >= sup and cl["sd"] >= c.get("sd_min", 0.0)

        if c.get("prior", True) and ref["valid"]:
            cands = [cl for cl in cls if ok(cl, c["prior_min"], c.get("sup_prior", 1))
                     and self.within(ref, cl["med"])]
            if cands:
                best = max(cands, key=score)
                return best["med"], best["n"]
        dom = [cl for cl in cls if ok(cl, c["dom_min"], c.get("sup_dom", 1))]
        if not dom:
            return None, 0
        top = dom[0]
        second = dom[1]["n"] if len(dom) > 1 else 0
        if top["n"] >= c.get("pool_ratio", 1.5) * second:
            return top["med"], top["n"]
        return None, 0


# ---- konfiguracje ----
BASE = dict(S2.V0, cons="pool", half=1.5, prior_min=12, dom_min=12, pool_ratio=1.5,
            sup_prior=1, sup_dom=1, sd_min=0.0, mode="count", prior=True)


def mk(name, **kw):
    cfg = dict(BASE, name=name, **kw)
    return cfg


VARIANTS_D = [
    mk("V4 firmware (+-1.5, min12)"),
    mk("D1 prior min6", prior_min=6),
    mk("D2 prior min5", prior_min=5),
    mk("D3 prior min6 + sup3", prior_min=6, sup_prior=3, sup_dom=3),
    mk("D4 prior min5, sup3 prior", prior_min=5, sup_prior=3),
    mk("D5 prior min6 + reject tight sd<0.2", prior_min=6, sd_min=0.2),
    mk("D6 prior min6, waga n*serie", prior_min=6, mode="vote"),
    mk("D7 okno +-1.0, prior min6", prior_min=6, half=1.0),
    mk("D8 okno +-2.5, prior min6", prior_min=6, half=2.5),
    mk("D9 min6 + sup3 + sd>=0.2", prior_min=6, sup_prior=3, sup_dom=3, sd_min=0.2),
]

for _cfg in VARIANTS_D:
    S2.register(_cfg["name"], (lambda cfg: (lambda w, s: DLogic(cfg).run(w, s)))(_cfg))
S2.register("SUFIT (idealny czujnik)", S2.run_oracle)


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    skip = {"1.4.5 (v1.5.0)", "V0 (TX 1.4.7)", "V1 klastry probek"}
    names = [n for n in S2.VARIANTS if n not in skip]
    results = S2.run_all(names, runs)
    print(f"FAULTS={FAULTS} ECHO_P={ECHO_P} runs={runs}")
    print(S2.table(results, names))
