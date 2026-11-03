#!/usr/bin/env python3
"""
Zadanie B (V5): czujnik slepy i szybki powrot.

V5 = V4 (firmware 1.4.9, sim3.NewLogic4) + SONDY: gdy cykl konczy sie NO_VALID, zaplanuj skrocone
pomiary po przerwach BO (domyslnie 30 / 60 / 120 min, kumulatywnie 30, 90, 210 min od cyklu).

Tryby:
  off   - kontrola (bez sond); powinna dac wyniki zblizone do V4
  blind - sondy tylko gdy statystyka probek wskazuje czujnik slepy:
          >= BLIND_INV % probek to timeout/poza zakresem (> 170 cm) i <= BLIND_VALID % poprawnych
  any   - sondy po kazdym NO_VALID (bez klasyfikacji)
Limit: CAP sond na 24 h (krocząco). Sonda nie wychodzi poza margines przed regularnym cyklem.

Sonda = skrocony pomiar (probe_series serii zamiast 6). Udany pomiar -> wysylka (z retry jak w V4).

Uruchomienie:
  python b_logic.py [liczba_przebiegow]              (FAULTS=1 domyslnie; FAULTS=0 = kontrola regresji)
  B_SCEN=transient python b_logic.py [runs]          (blind 2-10 h zamiast 12-48 h)
"""
import os
import random
import statistics
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
SYM = os.path.dirname(HERE)
if SYM not in sys.path:
    sys.path.insert(0, SYM)

import sim2 as M  # noqa: E402
import sim3 as T  # noqa: E402
from sim2 import MIN_VALID, SLEEP_S, Clock, Radio2, send_full  # noqa: E402

if os.environ.get("B_SCEN") == "transient":
    T.EP_TYPES = [("blind", 2, 10), ("blind", 2, 10), ("blind", 2, 10),
                  ("echo", 12, 36), ("echo", 12, 36), ("dz", 12, 48)]

MARGIN_S = 120          # nie planuj sondy/retry, jesli do regularnego cyklu zostaje mniej
BLIND_INV = 70          # % probek: timeout lub > 170 cm
BLIND_VALID = 35        # % probek poprawnych (25-170 cm) - maks. dla slepoty
BO_DEFAULT = [1800, 3600, 7200]   # przerwy miedzy kolejnymi sondami: 30, 60, 120 min
V4 = T.V4
HEAL_TOL = 8.0          # dostarczona wartosc "dobra", gdy |blad| <= 8 cm


def fresh():
    return dict(value=100.0, valid=False, cycles=0, rej=0, dz=0, t_acc=0.0)


def classify(st, c):
    tot = st["total"]
    if tot == 0:
        return "OTHER"
    inv = st["timeouts"] + st["above"]
    if inv * 100 >= c["blind_inv"] * tot and st["valid"] * 100 <= c["blind_valid"] * tot:
        return "BLIND"
    return "OTHER"


class NewLogic5(T.NewLogic4):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.now = 0.0
        self.last_class = "OTHER"

    # okno napelniania liczone z CZASU od ostatniej akceptacji (sondy nie zwieksza go sztucznie)
    def window(self, ref):
        days = max(0.0, self.now - ref["t_acc"]) / 24.0
        return self.cfg["fill_day"] * days + self.cfg["noise"]

    def within(self, ref, v):
        c = self.cfg
        delta = v - ref["value"]
        if delta > c["noise"]:
            return v >= c["empty_zone"]
        return delta >= -self.window(ref)

    def accept(self, ref, v):
        super().accept(ref, v)
        ref["t_acc"] = self.now

    def cycle(self, sensor, clock, ref, n=None):
        c = self.cfg
        self.now = clock.s / 3600.0
        n = n or c["n_series"]
        sensor.begin_cycle(n)
        st = dict(total=0, valid=0, below=0, above=0, timeouts=0)
        pool = []
        for s in range(n):
            self.series(sensor, clock, st, pool)
            if s < n - 1:
                clock.s += c["int_s"]
        self.last_class = classify(st, c)
        val, _ = self.cons_pool(pool, st, ref)
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

    def want_probe(self, c):
        if c["probe_mode"] == "any":
            return True
        return c["probe_mode"] == "blind" and self.last_class == "BLIND"

    def next_probe(self, p, now_s, next_reg, probe_t, c):
        """p = liczba sond juz wykonanych w tym lancuchu. Zwraca dict(p, due) albo None."""
        if p >= len(c["bo"]):
            return None
        due = now_s + c["bo"][p]
        if due >= next_reg - MARGIN_S:
            return None
        due_h = due / 3600.0
        if sum(1 for t in probe_t if due_h - 24.0 < t <= due_h) >= c["cap"]:
            return None
        return dict(p=p + 1, due=due)

    def run(self, world, seed):
        c = self.cfg
        clock, rng = Clock(), random.Random(seed * 7919 + 2)
        sensor, radio = M.Sensor2(world, rng, clock), Radio2(world, rng, clock)
        ref = fresh()
        acks, cycles, awake = [], [], 0.0
        resets = list(world.resets)
        clock.s = 0.1 * 3600
        end = world.H * 3600
        next_reg = clock.s
        wake = "REG"
        pend = None
        probe = None
        probe_t = []
        while clock.s < end:
            a0 = clock.s
            cyc = None
            radio.discover()
            if wake == "RETRY":
                if c["remeasure"] and world.rx_up(clock.s / 3600):
                    v2, _ = self.cycle(sensor, clock, ref)
                    if v2 is not None:
                        pend["value"], pend["t_meas"] = v2, clock.s / 3600
                if send_full(radio, clock):
                    acks.append((clock.s / 3600, pend["value"], pend["t_meas"]))
                    pend = None
                    nxt, wake = next_reg, "REG"
                else:
                    pend["k"] += 1
                    if pend["k"] <= len(c["retry"]):
                        nxt = min(clock.s + c["retry"][pend["k"] - 1], next_reg)
                        wake = "RETRY" if nxt < next_reg - 1 else "REG"
                    else:
                        pend = None
                        nxt, wake = next_reg, "REG"
            elif wake == "PROBE":
                probe_t.append(clock.s / 3600)
                value, status = self.cycle(sensor, clock, ref, n=c["probe_series"])
                t_meas = clock.s / 3600
                cyc = dict(t=a0 / 3600, value=value, status="PROBE_" + status, sent=False,
                           cls=self.last_class, kind="probe")
                pr = probe
                probe = None
                if value is not None:
                    if send_full(radio, clock):
                        acks.append((clock.s / 3600, value, t_meas))
                        cyc["sent"] = True
                        nxt, wake = next_reg, "REG"
                    elif c["retry"] and clock.s + c["retry"][0] < next_reg - 1:
                        pend = dict(value=value, t_meas=t_meas, k=1)
                        nxt, wake = clock.s + c["retry"][0], "RETRY"
                    else:
                        nxt, wake = next_reg, "REG"
                else:
                    nxt_probe = self.next_probe(pr["p"], clock.s, next_reg, probe_t, c) \
                        if self.want_probe(c) else None
                    if nxt_probe is not None:
                        probe = nxt_probe
                        nxt, wake = probe["due"], "PROBE"
                    else:
                        nxt, wake = next_reg, "REG"
            else:  # REG
                pend = None
                probe = None
                value, status = self.cycle(sensor, clock, ref)
                t_meas = clock.s / 3600
                cyc = dict(t=a0 / 3600, value=value, status=status, sent=False,
                           cls=self.last_class, kind="reg")
                next_reg = clock.s + SLEEP_S
                nxt, wake = next_reg, "REG"
                if value is not None:
                    if send_full(radio, clock):
                        acks.append((clock.s / 3600, value, t_meas))
                        cyc["sent"] = True
                    elif c["retry"] and clock.s + c["retry"][0] < next_reg - 1:
                        pend = dict(value=value, t_meas=t_meas, k=1)
                        nxt, wake = clock.s + c["retry"][0], "RETRY"
                elif status == "NO_VALID" and self.want_probe(c):
                    nxt_probe = self.next_probe(0, clock.s, next_reg, probe_t, c)
                    if nxt_probe is not None:
                        probe = nxt_probe
                        nxt, wake = probe["due"], "PROBE"

            if cyc is not None:
                cycles.append(cyc)
            awake += clock.s - a0
            if resets and resets[0] * 3600 <= nxt:
                nxt = resets.pop(0) * 3600 + 30
                pend = None
                probe = None
                if c["persist"] and ref["valid"]:
                    ref["cycles"] += 1
                    ref["rej"] = ref["dz"] = 0
                    ref["t_acc"] -= SLEEP_S / 3600.0  # jak w sim2: +1 cykl (12 h) od ostatniej akceptacji
                else:
                    ref = fresh()
                next_reg = nxt
                wake = "REG"
            clock.s = nxt
        return acks, cycles, awake


CFGS = {}


def cfg(name, **kw):
    base = dict(probe_mode="off", probe_series=6, bo=BO_DEFAULT, cap=3, blind_inv=BLIND_INV,
                blind_valid=BLIND_VALID)
    base.update(kw)
    return dict(V4, name=name, **base)


CFGS["V5 off (kontrola)"] = cfg("V5 off (kontrola)", probe_mode="off")
CFGS["B1 blind, 6 serii, cap 3"] = cfg("B1 blind, 6 serii, cap 3", probe_mode="blind", probe_series=6, cap=3)
CFGS["B2 blind, 2 serie, cap 3"] = cfg("B2 blind, 2 serie, cap 3", probe_mode="blind", probe_series=2, cap=3)
CFGS["B3 blind, 6 serii, cap 6"] = cfg("B3 blind, 6 serii, cap 6", probe_mode="blind", probe_series=6, cap=6)
CFGS["B4 any, 6 serii, cap 3"] = cfg("B4 any, 6 serii, cap 3", probe_mode="any", probe_series=6, cap=3)

for _name, _c in CFGS.items():
    M.register(_name, (lambda cc: (lambda w, s: NewLogic5(cc).run(w, s)))(_c))


def extra_one(args):
    """Statystyki dodatkowe: sondy, trafnosc wykrycia slepoty, falszywe flagi, czas powrotu po slepocie."""
    name, seed = args
    w = T.World3(seed)
    acks, cycles, awake = M.VARIANTS[name](w, seed)
    nprobe = pok = nb = tp = nf = fp = 0
    for cy in cycles:
        if cy.get("kind") == "probe":
            nprobe += 1
            pok += cy["value"] is not None
        if cy["status"] in ("NO_VALID", "PROBE_NO_VALID"):
            ep = w.episode(cy["t"])
            if ep == "blind":
                nb += 1
                tp += cy.get("cls") == "BLIND"
            elif ep in ("echo", "echo_long", "dz"):
                nf += 1
                fp += cy.get("cls") == "BLIND"
    rec, n_blind = [], 0
    for _s, e, kind in w.episodes:
        if kind != "blind":
            continue
        n_blind += 1
        good = [a[0] - e for a in acks
                if a[2] >= e and abs(a[1] - max(w.truth(a[2]), MIN_VALID)) <= HEAL_TOL]
        rec.append(min(good) if good else None)
    return dict(probes=nprobe, probe_ok=pok, nb=nb, tp=tp, nf=nf, fp=fp, rec=rec, n_blind=n_blind,
                awake=awake / 60.0)


def extras(names, runs):
    jobs = [(nm, s) for nm in names for s in range(1, runs + 1)]
    with Pool() as p:
        res = p.map(extra_one, jobs, chunksize=8)
    by = {}
    for (nm, _s), r in zip(jobs, res):
        by.setdefault(nm, []).append(r)
    lines = []
    for nm in names:
        rs = by[nm]
        n = len(rs)
        probes = sum(r["probes"] for r in rs) / n
        pok = sum(r["probe_ok"] for r in rs) / n
        nb, tp = sum(r["nb"] for r in rs), sum(r["tp"] for r in rs)
        nf, fp = sum(r["nf"] for r in rs), sum(r["fp"] for r in rs)
        rec_all = [x for r in rs for x in r["rec"]]
        ok = sorted(x for x in rec_all if x is not None)
        med = statistics.median(ok) if ok else float("nan")
        p95 = ok[min(len(ok) - 1, int(0.95 * len(ok)))] if ok else float("nan")
        never = 100.0 * (len(rec_all) - len(ok)) / len(rec_all) if rec_all else float("nan")
        pct = lambda a, b: (100.0 * a / b) if b else float("nan")
        lines.append(
            f"| {nm} | {probes:.2f} | {pok:.2f} | {pct(tp, nb):.0f} ({tp}/{nb}) | "
            f"{pct(fp, nf):.0f} ({fp}/{nf}) | {med:.1f} / {p95:.1f} ({never:.0f}%) |")
    return lines


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    names = ["SUFIT (idealny czujnik)", V4["name"]] + list(CFGS)
    res = T.run(names, runs)
    print(f"FAULTS={int(T.FAULTS)}, SCEN={os.environ.get('B_SCEN', 'default')}, przebiegow: {runs}\n")
    print(M.table(res, names))
    cols = [res[k] for k in names]
    print("| Falszywe \"pelny\" (<= 30 cm przy poziomie >= 40) [szt./50 dni] | "
          + " | ".join(f"{r['falsefull']:.2f}" for r in cols) + " |")
    print("| Przebiegi z >= 1 falszywym \"pelny\" [%] | "
          + " | ".join(f"{r['ff_runs']:.0f}" for r in cols) + " |")
    print("\n| Wariant | sondy/przebieg | sondy OK/przebieg | wykrycie slepoty (NO_VALID w blind) | "
          "falszywe flagi (NO_VALID w echo/dz) | powrot po slepocie mediana / p95 [h] (nie wrocil) |")
    print("|---|---|---|---|---|---|")
    print("\n".join(extras(names[1:], runs)))
