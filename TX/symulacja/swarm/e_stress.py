#!/usr/bin/env python3
"""
E - adwersarz: test obciazeniowy logiki V3 (TX 1.4.8-like, sim2.V3) i V4 (firmware 1.4.9, sim3.NewLogic4).

Swiat: World3 z sim3 (epizody z logu: echo, echo_long, blind, dz) + PWL (profil po punktach) dla scenariuszy
E, F, N, S. Dodatkowe bledy czujnika: podklasa AdvSensor(sim3.Sensor3) z warstwa Fault. Warstwa Fault jest
podpieta przez atrybut swiata `world.fault`, a `sim2.Sensor2` jest podmieniony na AdvSensor, wiec KAZDY wariant
z rejestru sim2.VARIANTS (w tym inne warianty dopisane przez innych) dostaje te same bledy.

Scenariusze A-N: jak w swarm_v1_old/stress.py (A-N zachowane), ale na swiecie World3 (z epizodami z logu).
Nowe: O (dwie awarie odbiornika pod rzad), P (echo na losowej odleglosci, przerywane), Q (czujnik wyjety:
stala 'sciana' 30-150), R (wywoz rownoczesnie z echem 25.4), S (zbiornik naprawde pelny: schodzi do 20 cm,
ma isc 25.0 po 3 cyklach), T (dwa kolejne cykle zepsute, losowe 25-170). D (dryf) jest w A-N.

Metryki: dobry widok %, grube bledy (>20 cm) szt./50 dni, P(>=1 gruby) %, falszywe "pelny" (<=30 przy prawdzie
>=40), falszywe 25.0 (przy prawdzie >=40), najdluzsza blokada (kolejne godziny z bledem widoku >10 cm),
opoznienie wykrycia wywozu (h, mediana; nie wykryto %), opoznienie 25.0 po wejsciu poziomu w strefe martwa (S).

Uruchomienie:
    python e_stress.py [liczba_przebiegow=120]
    -> wypisuje tabele i zapisuje ROOT\\symulacja\\swarm\\e_stress_wyniki.md

Dodanie wlasnego wariantu logiki jako kolumny:
    1. W osobnym module (importowanym przed uruchomieniem, na poziomie modulu, nie w if __name__):
           import sim2 as M
           M.register("MOJ WARIANT", fn)     # fn(world, seed) -> (acks, cycles, awake), jak w sim2
    2. Wywolaj compare(["V3 (rekomendowana)", "V4 (v1.7.1 poprawki)", "MOJ WARIANT"], runs)
       albo report(...). Dla workerow Windows (spawn) rejestracja musi byc na poziomie modulu.
Uwaga: sim2.NewLogic.run zapisuje odniesienie po resecie z przyrostem +1 cykl (sim2), a firmware
REF_RESTORE_EXTRA_CYCLES = 2 (main.cpp:89). Roznica istnieje w symulacji, nie zostala zmieniona.
"""
import bisect
import math
import os
import random
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
SYM = os.path.dirname(HERE)
if SYM not in sys.path:
    sys.path.insert(0, SYM)

import sim as S  # noqa: E402
import sim2 as M  # noqa: E402
import sim3 as T  # noqa: E402  (World3, Sensor3, NewLogic4, rejestruje V4; importuje iter_final -> V3)

MIN_VALID = 25.0
TOL = 10.0            # widok "dobry" / blokada
BAD_ERR = 8.0
BIG_ERR = 20.0
FALSE_DZ_TRUTH = 40.0
FALSEFULL_MAX = 30.0
DEFAULT_RUNS = 120
DEFAULT_VARIANTS = ["V3 (rekomendowana)", "V4 (v1.7.1 poprawki)"]


# ======================= PODKLASA CZUJNIKA Z WARSTWA BLEDOW =======================
class AdvSensor(T.Sensor3):
    """Sensor3 + warstwa Fault. Fault jest czytany z world.fault (None = brak dodatkowych bledow)."""

    def begin_cycle(self, n_series):
        super().begin_cycle(n_series)
        self.cyc = getattr(self, "cyc", 0) + 1
        f = getattr(self.w, "fault", None)
        if f is not None:
            f.cycle_start(self)

    def measure(self):
        d = super().measure()
        f = getattr(self.w, "fault", None)
        return d if f is None else f.apply(self, d)


# Warianty z sim2 (NewLogic.run, run_old) tworza Sensor2 przez globalna nazwe w sim2 -> podmieniamy.
M.Sensor2 = AdvSensor


# ======================= PWL (profil po punktach) =======================
class PWL:
    """Odleglosc (cm) w funkcji dnia; dwa punkty o tym samym dniu = skok (wywoz)."""

    def __init__(self, pts, pumps):
        self.H = 50 * 24.0
        self.pts = pts
        self.times = [p[0] for p in pts]
        self.pumps = list(pumps)
        self.resets, self.outages, self.removals = [], [], []

    def truth(self, th):
        td = th / 24.0
        i = bisect.bisect_right(self.times, td) - 1
        if i < 0:
            d = self.pts[0][1]
        elif i >= len(self.pts) - 1:
            d = self.pts[-1][1]
        else:
            t0, d0 = self.pts[i]
            t1, d1 = self.pts[i + 1]
            d = d0 + (d1 - d0) * (td - t0) / (t1 - t0) if t1 > t0 else d0
        return max(8.0, d)

    def removal(self, th):
        return None

    def rx_up(self, th):
        return not any(a <= th < b for a, b in self.outages)


def pwl_dz(r):
    """Pelny zbiornik: fill do 20 cm, plateau, wywoz do 160, ponowne napelnianie, plateau."""
    rate = r.uniform(7, 9)
    t1 = (150 - 20) / rate
    t2 = 30.0 + (160 - 20) / rate
    return PWL([(0.0, 150.0), (t1, 20.0), (30.0, 20.0), (30.0, 160.0), (t2, 20.0), (60.0, 20.0)], [30.0])


def pwl_fast(r):
    """Szybkie napelnianie 26-30 cm/dobe, wywoz co ~4 dni do 150 cm."""
    rate = r.uniform(26, 30)
    pts, pumps, t = [(0.0, 150.0)], [], 0.0
    while t < 50:
        t_end = t + 110.0 / rate
        pts.append((t_end, 40.0))
        pts.append((t_end, 150.0))
        pumps.append(t_end)
        t = t_end
    return PWL(pts, pumps)


def pwl_pump_partial(r):
    """Czesciowe wywozy 70 -> 128 cm (skok < 140 cm), napelnianie 7-9 cm/dobe."""
    rate = r.uniform(7, 9)
    pts, pumps, t, d = [(0.0, 150.0)], [], 0.0, 150.0
    while t < 50:
        t1 = t + (d - 70.0) / rate
        pts.append((t1, 70.0))
        pts.append((t1, 128.0))
        pumps.append(t1)
        t, d = t1, 128.0
    return PWL(pts, pumps)


def pwl_full_desc(r):
    """Zbiornik naprawde pelny: poziom schodzi z 150 do 20 cm i stoi do konca (bez wywozu)."""
    rate = r.uniform(4.5, 6.0)
    t1 = (150 - 20) / rate
    return PWL([(0.0, 150.0), (t1, 20.0), (60.0, 20.0)], [])


# ======================= SCENARIUSZE =======================
SCN = [
    dict(name="A baseline (World3 z epizodami z logu)", kind="none", world="W3"),
    dict(name="B falszywe echo losowe 30-150 cm, p 30-80%/cykl", kind="ghost_persist", world="W3"),
    dict(name="C falszywe echo co 2. cykl (p 70%)", kind="ghost_alt", world="W3"),
    dict(name="D dryf czujnika +-0.3-0.6 cm/dobe (max 12 cm)", kind="drift", world="W3"),
    dict(name="E prawdziwa strefa martwa (plateau 20 cm)", kind="none", world="pwl_dz"),
    dict(name="F szybkie napelnianie 26-30 cm/dobe", kind="none", world="pwl_fast"),
    dict(name="G wywoz + 3 cykle stabilnego bledu 90-130", kind="pump_fault", world="W3"),
    dict(name="H reset tuz po wywozie + falszywe echo", kind="reset_ghost", world="W3", reset_at_pump=True),
    dict(name="I jeden cykl 'sciana' 145 cm (100% probek)", kind="single145", world="W3"),
    dict(name="J 3 z 6 serii stale zle (ta sama wartosc)", kind="half_same", world="W3"),
    dict(name="K 3 z 6 serii zle (losowe wartosci)", kind="half_random", world="W3"),
    dict(name="L krotkie echo 18 cm (60%), prawda 15% probek", kind="dz_false", share=0.15, world="W3"),
    dict(name="M kontrola: krotkie echo 18 cm, prawda 25%", kind="dz_false", share=0.25, world="W3"),
    dict(name="N wywoz czesciowy 70->128 + blackout 3 cykle", kind="blackout", world="pwl_pump"),
    dict(name="O dwie awarie odbiornika pod rzad (24 h + 24 h)", kind="none", world="W3", outage="double"),
    dict(name="P echo na losowej odleglosci 30-150, przerywane (2 okna)", kind="intermittent", world="W3"),
    dict(name="Q czujnik wyjety: stala sciana 30-150 (24-48 h)", kind="wall", world="W3"),
    dict(name="R wywoz rownoczesnie z echem 25.4 (50% probek, +-1 dzien)", kind="pump_echo", world="W3"),
    dict(name="S zbiornik naprawde pelny: schodzi do 20 cm, ma isc 25.0", kind="none", world="pwl_full"),
    dict(name="T dwa kolejne cykle zepsute (losowe 25-170)", kind="two_bad", world="W3"),
]


def build_world(spec, seed):
    r = random.Random(seed * 104729 + 7)
    kind = spec["world"]
    if kind == "W3":
        w = T.World3(seed)
    elif kind == "pwl_dz":
        w = pwl_dz(r)
    elif kind == "pwl_fast":
        w = pwl_fast(r)
    elif kind == "pwl_pump":
        w = pwl_pump_partial(r)
    elif kind == "pwl_full":
        w = pwl_full_desc(r)
    else:
        raise ValueError(kind)
    if spec.get("reset_at_pump"):
        w.resets = sorted(p * 24 + 0.5 for p in w.pumps)
    if spec.get("outage") == "double":
        s = r.uniform(2 * 24, 40 * 24)
        w.outages = [(s, s + 24), (s + 24, s + 48)]   # dwie awarie pod rzad
    w.fault = None
    return w


class Fault:
    """Dodatkowe bledy czujnika. cycle_start() ustawia stan na cykl, apply() modyfikuje pojedynczy pomiar."""

    def __init__(self, kind, r, world, share=0.25):
        self.k, self.share, self.w, self.r = kind, share, world, r
        self.X = r.uniform(30, 150)           # staly falszywy odczyt
        self.Xp = r.uniform(90, 130)          # falszywy odczyt po wywozie
        self.H = set(r.sample(range(6), 3))
        self.c0 = r.randint(10, 60)           # poczatek cyklu (single145, two_bad)
        self.drift = r.choice([-1.0, 1.0]) * r.uniform(0.3, 0.6)
        self.p, self.gv, self.act, self.xs = 0.0, self.X, False, {}
        self.win = []                         # okna czasowe (h): (od, do, wartosc)
        if kind == "intermittent":
            for _ in range(2):
                a = r.uniform(3 * 24, 44 * 24)
                self.win.append((a, a + r.uniform(24, 72), r.uniform(30, 150)))
        elif kind == "wall":
            a = r.uniform(3 * 24, 44 * 24)
            self.win = [(a, a + r.uniform(24, 48), r.uniform(30, 150))]

    def cycle_start(self, sn):
        th, r, k = sn.c.h(), self.r, self.k
        self.p, self.gv, self.act = 0.0, self.X, False
        if k == "ghost_persist":
            self.p = r.uniform(0.3, 0.8)
        elif k == "ghost_alt":
            self.p = 0.7 if sn.cyc % 2 == 0 else 0.0
        elif k == "pump_fault":
            if any(p * 24 <= th <= p * 24 + 36 for p in self.w.pumps):
                self.p, self.gv = 0.6, self.Xp
        elif k == "reset_ghost":
            if any(x <= th <= x + 36 for x in self.w.resets):
                self.p = 0.4
        elif k == "single145":
            self.act = sn.cyc == self.c0
        elif k == "half_random":
            self.xs = {s: r.uniform(30, 150) for s in range(6)}

    def apply(self, sn, base):
        r, k = self.r, self.k
        th = sn.c.h()
        if k in ("ghost_persist", "ghost_alt", "pump_fault", "reset_ghost"):
            if self.p > 0 and r.random() < self.p:
                return self.gv + r.gauss(0, 0.4)
            return base
        if k == "drift":
            if base < 0:
                return base
            return base + max(-12.0, min(12.0, self.drift * th / 24.0))
        if k == "single145":
            return 145.0 + r.gauss(0, 0.4) if self.act else base
        if k == "half_same":
            return self.X + r.gauss(0, 0.4) if sn.idx in self.H else base
        if k == "half_random":
            return self.xs[sn.idx] + r.gauss(0, 0.4) if sn.idx in self.H else base
        if k == "dz_false":
            u = r.random()
            if u < 0.6:
                return 18.0 + r.gauss(0, 0.4)
            if u < 0.6 + self.share:
                return self.w.truth(th) + r.gauss(0, 0.4)
            return -1.0
        if k == "blackout":
            return -1.0 if any(p * 24 - 6 <= th <= p * 24 + 30 for p in self.w.pumps) else base
        if k == "two_bad":
            if sn.cyc in (self.c0, self.c0 + 1):
                return r.uniform(25, 170) if r.random() < 0.9 else -1.0
            return base
        if k == "intermittent":
            for a, b, x in self.win:
                if a <= th < b and r.random() < 0.5:
                    return x + r.gauss(0, 0.4)
            return base
        if k == "wall":
            for a, b, x in self.win:
                if a <= th < b:
                    return x + r.gauss(0, 0.5)
            return base
        if k == "pump_echo":
            if any(p * 24 - 6 <= th <= p * 24 + 36 for p in self.w.pumps) and r.random() < 0.5:
                return max(25.05, r.gauss(25.4, 0.2))
            return base
        return base  # "none"


# ======================= METRYKI =======================
def metrics(acks, cycles, world):
    m = M.metrics(acks, cycles, 0.0, world)
    sa = sorted(acks)
    ta = [a[0] for a in sa]
    longest = cur = 0
    for h in range(2, int(world.H)):
        i = bisect.bisect_right(ta, h) - 1
        bad = i < 0 or abs(sa[i][1] - max(world.truth(h), MIN_VALID)) > TOL
        cur = cur + 1 if bad else 0
        longest = max(longest, cur)
    m["longest_bad_h"] = longest
    m["fdz"] = sum(1 for a in acks if a[1] == MIN_VALID and world.truth(a[2]) >= FALSE_DZ_TRUTH)
    m["falsefull"] = sum(1 for a in acks if a[1] <= FALSEFULL_MAX and world.truth(a[2]) >= FALSE_DZ_TRUTH)
    t0 = next((h for h in range(0, int(world.H)) if world.truth(h) < MIN_VALID), None)
    lat = None
    if t0 is not None:
        for a in sa:
            if a[2] >= t0 and a[1] == MIN_VALID:
                lat = a[2] - t0
                break
    m["dz_lat"] = lat
    return m


def one(args):
    idx, vname, seed = args
    spec = SCN[idx]
    w = build_world(spec, seed)
    w.fault = Fault(spec["kind"], random.Random(seed * 1000003 + idx * 97 + 5), w, spec.get("share", 0.25))
    acks, cycles, awake = M.VARIANTS[vname](w, seed)
    return idx, vname, metrics(acks, cycles, w)


def median(v):
    v = sorted(v)
    n = len(v)
    if n == 0:
        return float("nan")
    return (v[n // 2 - 1] + v[n // 2]) / 2.0 if n % 2 == 0 else v[n // 2]


def agg(ms):
    n = len(ms)
    avg = lambda k: sum(m[k] for m in ms) / n
    longs = sorted(m["longest_bad_h"] for m in ms)
    pv = [x for m in ms for x in m["pump"] if x is not None]
    pt = sum(len(m["pump"]) for m in ms)
    pnever = sum(1 for m in ms for x in m["pump"] if x is None)
    lv = [m["dz_lat"] for m in ms if m["dz_lat"] is not None]
    return dict(
        good=avg("good"), big_n=avg("big_n"),
        p_big=100.0 * sum(1 for m in ms if m["big_n"] > 0) / n,
        falsefull=avg("falsefull"), fdz=avg("fdz"),
        long_med=longs[n // 2], long_max=longs[-1],
        pump_med=median(pv), pump_never=(100.0 * pnever / pt) if pt else None,
        dz_med=median(lv) if lv else None, dz_hit=100.0 * len(lv) / n,
    )


# ======================= URUCHOMIENIE / RAPORT =======================
def compare(names, runs=DEFAULT_RUNS, idxs=None):
    """Zwraca {(indeks_scenariusza, nazwa_wariantu): [metryki po przebiegach]}.
    names: nazwy z sim2.VARIANTS (kazdy wariant musi byc zarejestrowany na poziomie modulu)."""
    idxs = list(range(len(SCN))) if idxs is None else list(idxs)
    jobs = [(i, v, s) for i in idxs for v in names for s in range(1, runs + 1)]
    with Pool() as p:
        res = p.map(one, jobs, chunksize=8)
    by = {}
    for i, v, m in res:
        by.setdefault((i, v), []).append(m)
    return by


def table(by, names, runs, idxs=None):
    idxs = list(range(len(SCN))) if idxs is None else list(idxs)
    L = [f"Przebiegow na scenariusz i wariant: {runs} (50 dni, cykl 12 h). Kolumny: wartosci dla kazdego wariantu, "
         f"oddzielone ' / ' w kolejnosci: {' | '.join(names)}", ""]
    L.append("| Scenariusz | dobry widok % | grube bledy >20 cm (szt./50 dni) | P(>=1 gruby) % | "
             "falszywe 'pelny' (<=30 przy >=40) szt. | falszywe 25.0 (prawda >=40) szt. | "
             "blokada >10 cm [h] med / max | wywoz: wykrycie med [h] (nie wykryto %) | "
             "25.0 po wejsciu w strefe martwa [h] med (trafienia %) |")
    L.append("|---|---|---|---|---|---|---|---|---|")

    def cell(vals, fmt):
        return " / ".join(fmt(a) for a in vals)

    for i in idxs:
        A = [agg(by[(i, v)]) for v in names]
        L.append(
            f"| {SCN[i]['name']} | "
            + cell(A, lambda a: f"{a['good']:.1f}") + " | "
            + cell(A, lambda a: f"{a['big_n']:.2f}") + " | "
            + cell(A, lambda a: f"{a['p_big']:.0f}") + " | "
            + cell(A, lambda a: f"{a['falsefull']:.2f}") + " | "
            + cell(A, lambda a: f"{a['fdz']:.2f}") + " | "
            + cell(A, lambda a: f"{a['long_med']} / {a['long_max']}") + " | "
            + cell(A, lambda a: ("-" if a["pump_med"] != a["pump_med"] else f"{a['pump_med']:.1f} ({a['pump_never']:.0f}%)")) + " | "
            + cell(A, lambda a: ("-" if a["dz_med"] is None else f"{a['dz_med']:.1f} ({a['dz_hit']:.0f}%)")) + " |"
        )
    return "\n".join(L)


def report(names=None, runs=DEFAULT_RUNS, out_name="e_stress_wyniki.md"):
    names = list(names or DEFAULT_VARIANTS)
    by = compare(names, runs)
    txt = table(by, names, runs)
    print(txt)
    with open(os.path.join(HERE, out_name), "w", encoding="utf-8") as f:
        f.write("# E - adwersarz V3 / V4 (e_stress.py)\n\n" + txt + "\n")
    return by


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RUNS
    report(DEFAULT_VARIANTS, runs)
