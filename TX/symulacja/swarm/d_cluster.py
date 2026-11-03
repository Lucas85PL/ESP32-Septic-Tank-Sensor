#!/usr/bin/env python3
"""
Wariant D - lepszy wybor klastra (podklasa NewLogic4 = V4 / firmware 1.4.9) na modelu sim3.

Zmiany wzgledem V4 (kazda sterowana konfiguracja, domyslnie = V4):
 (1) prior_min / sup_prior: prog min. probek dla klastra zgodnego z oczekiwanym zakresem
     obnizony, ale tylko gdy klaster ma wsparcie z >= sup_prior roznych serii
 (2) mode="vote": wybor sposrod klastrow zgodnych z oczekiwaniem wg n * liczba_serii
 (3) sd_min: odrzucenie klastra o nienaturalnie malym rozrzucie (sd < sd_min cm)
 (4) vote dotyczy takze wyboru klastra (jak wyzej)
 (5) half: polowa szerokosci okna klastra

Uruchomienie (z katalogu symulacja):
   set FAULTS=1 & python swarm\\d_cluster.py 150
   set FAULTS=0 & python swarm\\d_cluster.py 150
"""
import bisect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import sim2 as M  # noqa: E402
import sim3 as T  # noqa: E402  (rejestruje V4 w sim2, modele bledow z logu)


class DLogic(T.NewLogic4):
    def cycle(self, sensor, clock, ref):
        self._sid = 0
        return super().cycle(sensor, clock, ref)

    def series(self, sensor, clock, st, collect):
        tmp = []
        m = super().series(sensor, clock, st, tmp)
        collect.extend((v, self._sid) for v in tmp)
        self._sid += 1
        return m

    def clusters(self, pool):
        c = self.cfg
        w = 2.0 * c.get("half", 1.5)
        s = sorted(pool)
        vals = [x[0] for x in s]
        out = []
        for _ in range(3):
            if not s:
                break
            best_i, best_n = 0, 0
            for i in range(len(s)):
                j = bisect.bisect_right(vals, vals[i] + w)
                if j - i > best_n:
                    best_i, best_n = i, j - i
            cl = s[best_i:best_i + best_n]
            vs = [x[0] for x in cl]
            mu = sum(vs) / len(vs)
            sd = (sum((x - mu) ** 2 for x in vs) / len(vs)) ** 0.5
            sids = sorted({x[1] for x in cl})
            out.append(dict(n=best_n, med=M.med(vs), sids=len(sids),
                            span=(sids[-1] - sids[0] + 1) if sids else 0, sd=sd))
            s = s[:best_i] + s[best_i + best_n:]
            vals = [x[0] for x in s]
        return out

    def cons_pool(self, pool, st, ref):
        c = self.cfg
        cls = self.clusters(pool)
        sd_min = c.get("sd_min", 0.0)
        span_min = c.get("span_min", 0)

        def ok(cl, min_n, sup):
            return (cl["n"] >= min_n and cl["sids"] >= sup and cl["sd"] >= sd_min
                    and cl["span"] >= span_min)

        def score(cl):
            return cl["n"] * cl["sids"] if c.get("mode") == "vote" else cl["n"]

        if c.get("prior", True) and ref["valid"]:
            cands = [cl for cl in cls if ok(cl, c["prior_min"], c.get("sup_prior", 1))
                     and self.within(ref, cl["med"])]
            if cands:
                best = max(cands, key=score)  # max() zwraca pierwszy najwiekszy, jak w V4
                return best["med"], best["n"]
        dom = [cl for cl in cls if ok(cl, c["dom_min"], c.get("sup_dom", 1))]
        if not dom:
            return None, 0
        top = dom[0]
        second = dom[1]["n"] if len(dom) > 1 else 0
        if top["n"] >= c.get("pool_ratio", 1.5) * second:
            return top["med"], top["n"]
        return None, 0


# V4 = firmware 1.4.9 (prior_min=pool_min=12, bez sd, bez wsparcia serii)
BASE = dict(T.V4, prior=True, prior_min=12, dom_min=12, sup_prior=1, sup_dom=1,
            sd_min=0.0, span_min=0, mode="count", half=1.5, pool_ratio=1.5)


def mk(name, **kw):
    return dict(BASE, name=name, **kw)


VARIANTS_D = [
    mk("D0 kontrola = V4"),
    mk("D1 prior min6 sup3", prior_min=6, sup_prior=3),
    mk("D2 prior min5 sup3", prior_min=5, sup_prior=3),
    mk("D3 prior min6 sup2", prior_min=6, sup_prior=2),
    mk("D4 sd>=0.25 (tylko)", sd_min=0.25),
    mk("D5 prior min6 sup3 sd>=0.25", prior_min=6, sup_prior=3, sd_min=0.25),
    mk("D6 prior min6 sup3 vote", prior_min=6, sup_prior=3, mode="vote"),
    mk("D7 prior min6 sup3 span>=4", prior_min=6, sup_prior=3, span_min=4),
    mk("D8 prior min6 sup3 okno+-1.0", prior_min=6, sup_prior=3, half=1.0),
    mk("D9 prior min6 sup3 okno+-2.0", prior_min=6, sup_prior=3, half=2.0),
    mk("D10 prior min6 sup3 sd0.25 vote", prior_min=6, sup_prior=3, sd_min=0.25, mode="vote"),
]

NAMES_D = [c["name"] for c in VARIANTS_D]
for _cfg in VARIANTS_D:
    M.register(_cfg["name"], (lambda cfg: (lambda w, s: DLogic(cfg).run(w, s)))(_cfg))


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    names = ["SUFIT (idealny czujnik)", T.V3["name"], T.V4["name"]] + NAMES_D
    res = T.run(names, runs)
    txt = M.table(res, names)
    cols = [res[k] for k in names]
    txt += "\n| Falszywe \"pelny\" (<= 30 cm przy poziomie >= 40) [szt./50 dni] | " + " | ".join(
        f"{r['falsefull']:.2f}" for r in cols) + " |"
    txt += "\n| Przebiegi z >= 1 falszywym \"pelny\" [%] | " + " | ".join(
        f"{r['ff_runs']:.0f}" for r in cols) + " |"
    print(f"FAULTS={int(T.FAULTS)}, przebiegow: {runs}\n")
    print(txt)
