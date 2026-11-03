#!/usr/bin/env python3
"""
Adwersarz V4 (test obciazeniowy): zlosliwe scenariusze bledow czujnika.

Uwagi o zrodlach (sim3.py i wyniki3.md NIE istnieja w katalogu symulacja/):
 - swiat bazowy: World2 z sim2.py (pompowanie, awarie odbiornika, resety, wyjecia czujnika),
   a dla scenariuszy wymagajacych innego profilu: PWL (profil odleglosci po punktach),
 - czujnik: Sensor2 z sim2.py + warstwa bledow (Fault) nakladana na kazdy pomiar,
 - V4: wierny port src/measurement.cpp (klastry 3 cm, min 12 probek, okno napelniania,
   wywoz >= 140, po 2 odrzuconych cyklach akceptacja, strefa martwa 3 cykle -> 25.0 cm),
   odniesienie we flash: po resecie przywracane z wartoscia i oknem +2 cykle (zalozenie),
 - V3 (dla porownania): NewLogic(V0) z sim2.py = konsensus serii (TX 1.4.7), bez flash.

Uruchomienie:  python swarm/stress.py [liczba_przebiegow=120]
"""
import bisect
import os
import random
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sim2 as B  # noqa: E402  (World2, Sensor2, Clock, Radio2, send_full, metrics, NewLogic, V0)

MIN_V, MAX_V = 25.0, 170.0
DAYS = 50
SLEEP_S = 43200
TOL = 10.0     # widok "dobry"
BAD_ERR = 8.0  # dostarczona wartosc "bledna"
BIG_ERR = 20.0
FALSE_DZ_TRUTH = 40.0  # wyslane 25.0 gdy prawda >= 40 cm = falszywa strefa martwa

V3 = B.NewLogic(B.V0)


# ======================= SWIAT PWL (profil po punktach) =======================
class PWL:
    """Odleglosc (cm) w funkcji dnia; pary punktow o tym samym dniu = skok (wywoz)."""

    def __init__(self, pts, pumps):
        self.H = DAYS * 24.0
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
        return True


def pwl_dz(r):
    """Pelny zbiornik: fill do 20 cm, plateau do dnia 30, wywoz do 160, ponowne napelnianie, plateau."""
    rate = r.uniform(7, 9)
    t1 = (150 - 20) / rate
    t2 = 30.0 + (160 - 20) / rate
    return PWL([(0.0, 150.0), (t1, 20.0), (30.0, 20.0), (30.0, 160.0), (t2, 20.0), (60.0, 20.0)], [30.0])


def pwl_fast(r):
    """Szybkie napelnianie 26-30 cm/dobe, wywoz co ~4.5 dnia do 150 cm."""
    rate = r.uniform(26, 30)
    pts, pumps, t = [(0.0, 150.0)], [], 0.0
    while t < DAYS:
        t_end = t + 110.0 / rate
        pts.append((t_end, 40.0))
        pts.append((t_end, 150.0))
        pumps.append(t_end)
        t = t_end
    return PWL(pts, pumps)


def pwl_pump_partial(r):
    """Czesciowe wywozy 70 -> 128 cm (skok < 140 cm!), napelnianie 7-9 cm/dobe."""
    rate = r.uniform(7, 9)
    pts, pumps, t, d = [(0.0, 150.0)], [], 0.0, 150.0
    while t < DAYS:
        t1 = t + (d - 70.0) / rate
        pts.append((t1, 70.0))
        pts.append((t1, 128.0))
        pumps.append(t1)
        t, d = t1, 128.0
    return PWL(pts, pumps)


# ======================= SCENARIUSZE =======================
SCN = [
    dict(name="A baseline (sim2)", kind="none", world="W2"),
    dict(name="B falszywe echo losowe 30-150 cm, p 30-80%/cykl", kind="ghost_persist", world="W2"),
    dict(name="C falszywe echo co 2. cykl (p 70%)", kind="ghost_alt", world="W2"),
    dict(name="D dryf czujnika +-0.3-0.6 cm/dobe (max 12 cm)", kind="drift", world="W2"),
    dict(name="E prawdziwa strefa martwa (plateau 20 cm)", kind="none", world="pwl_dz"),
    dict(name="F szybkie napelnianie 26-30 cm/dobe", kind="none", world="pwl_fast"),
    dict(name="G wywoz + 3 cykle stabilnego bledu 90-130", kind="pump_fault", world="W2"),
    dict(name="H reset tuz po wywozie + falszywe echo", kind="reset_ghost", world="W2", reset_at_pump=True),
    dict(name="I jeden cykl 'sciana' 145 cm (100% probek)", kind="single145", world="W2"),
    dict(name="J 3 z 6 serii stale zle (ta sama wartosc)", kind="half_same", world="W2"),
    dict(name="K 3 z 6 serii zle (losowe wartosci)", kind="half_random", world="W2"),
    dict(name="L krotkie echo 18 cm (60%), prawda 15% probek", kind="dz_false", share=0.15, world="W2"),
    dict(name="M kontrola: krotkie echo 18 cm, prawda 25%", kind="dz_false", share=0.25, world="W2"),
    dict(name="N wywoz czesciowy 70->128 + blackout 3 cykle", kind="blackout", world="pwl_pump"),
]


def build_world(spec, seed):
    r = random.Random(seed * 104729 + 7)
    kind = spec["world"]
    if kind == "pwl_dz":
        w = pwl_dz(r)
    elif kind == "pwl_fast":
        w = pwl_fast(r)
    elif kind == "pwl_pump":
        w = pwl_pump_partial(r)
    else:
        w = B.World2(seed)
    if spec.get("reset_at_pump"):
        w.resets = sorted(p * 24 + 0.5 for p in w.pumps)
    return w


class Fault:
    def __init__(self, spec, r, world):
        self.k, self.share, self.w, self.r = spec["kind"], spec.get("share", 0.25), world, r
        self.X = r.uniform(30, 150)     # staly falszywy odczyt
        self.Xp = r.uniform(90, 130)    # falszywy odczyt po wywozie
        self.H = set(r.sample(range(6), 3))
        self.c0 = r.randint(10, 60)     # cykl z "145 cm"
        self.drift = r.choice([-1.0, 1.0]) * r.uniform(0.3, 0.6)
        self.p, self.gv, self.act, self.xs = 0.0, self.X, False, {}

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
        r, k, th = self.r, self.k, sn.c.h()
        if k in ("ghost_persist", "ghost_alt", "pump_fault", "reset_ghost"):
            if self.p > 0 and r.random() < self.p:
                return self.gv + r.gauss(0, 0.4)
            return base
        if k == "drift":
            return base + max(-12.0, min(12.0, self.drift * th / 24.0)) if base >= 0 else base
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
        return base


class AdvSensor(B.Sensor2):
    def __init__(self, world, rng, clock, fault):
        super().__init__(world, rng, clock)
        self.f, self.cyc = fault, 0

    def begin_cycle(self, n_series):
        super().begin_cycle(n_series)
        self.cyc += 1
        self.f.cycle_start(self)

    def measure(self):
        return self.f.apply(self, super().measure())


# ======================= V4 = port src/measurement.cpp =======================
def median(v):
    v = sorted(v)
    n = len(v)
    return (v[n // 2 - 1] + v[n // 2]) / 2.0 if n % 2 == 0 else v[n // 2]


def v4_clusters(pool):
    """pool: lista (wartosc, seria). Zachlanne okna 3 cm, do 3 klastrow (jak findClusters)."""
    s = sorted(pool)
    out = []
    for _ in range(3):
        if not s:
            break
        vals = [x[0] for x in s]
        best_i, best_n = 0, 0
        for i in range(len(s)):
            j = bisect.bisect_right(vals, vals[i] + 3.0)
            if j - i > best_n:
                best_i, best_n = i, j - i
        cl = s[best_i:best_i + best_n]
        out.append((best_n, median([x[0] for x in cl])))
        s = s[:best_i] + s[best_i + best_n:]
    return out


def v4_within(ref, v):
    days = (ref["cycles"] + 1) * (SLEEP_S / 86400.0)
    window = 15.0 * days + 5.0
    delta = v - ref["value"]
    if delta > 5.0:
        return v >= 140.0
    return delta >= -window


def v4_accept(ref, v):
    ref.update(value=v, valid=True, cycles=0, rej=0, dz=0)


def v4_cycle(sensor, clock, ref):
    sensor.begin_cycle(6)
    pool, below, total = [], 0, 0
    for s in range(6):
        for i in range(10):
            d = sensor.measure()
            total += 1
            if d < 0:
                pass
            elif d < MIN_V:
                below += 1
            elif d > MAX_V:
                pass
            else:
                pool.append((d, s))
            if i < 9:
                clock.s += 1.0
        if s < 5:
            clock.s += 20.0
    # konsensus
    cl = [c for c in v4_clusters(pool) if c[0] >= 12]
    chosen = None
    if cl and ref["valid"]:
        for c in cl:
            if v4_within(ref, c[1]):
                chosen = c
                break
    if chosen is None and cl:
        second = cl[1][0] if len(cl) > 1 else 0
        if cl[0][0] >= 1.5 * second:
            chosen = cl[0]
    if chosen is None:
        if below * 100 >= 50 * total and ref["valid"] and ref["value"] <= 70.0:
            if ref["dz"] < 3:
                ref["dz"] += 1
            if ref["dz"] >= 3:
                v4_accept(ref, MIN_V)
                ref["dz"] = 3
                return MIN_V, "DEADZONE"
        else:
            ref["dz"] = 0
        ref["cycles"] += 1
        return None, "NO_VALID"
    val = chosen[1]
    if not ref["valid"] or v4_within(ref, val) or ref["rej"] >= 2:
        v4_accept(ref, val)
        return val, "OK"
    ref["rej"] += 1
    ref["dz"] = 0
    ref["cycles"] += 1
    return None, "JUMP_REJECTED"


def fresh():
    return dict(value=100.0, valid=False, cycles=0, rej=0, dz=0)


# ======================= PRZEBIEG =======================
def drive(world, seed, fault, logic):
    clock = B.Clock()
    rng = random.Random(seed * 7919 + 17)
    sensor = AdvSensor(world, rng, clock, fault)
    radio = B.Radio2(world, rng, clock)
    ref, flash = fresh(), None   # flash: ostatnio zaakceptowana wartosc (tylko V4)
    acks, cycles, awake = [], [], 0.0
    resets = list(world.resets)
    clock.s = 0.1 * 3600
    end = world.H * 3600
    while clock.s < end:
        a0 = clock.s
        radio.discover()
        if logic == "V4":
            value, status = v4_cycle(sensor, clock, ref)
            if ref["valid"] and ref["cycles"] == 0:
                flash = ref["value"]
        else:
            value, status = V3.cycle(sensor, clock, ref)
        t_meas = clock.s / 3600
        cyc = dict(t=a0 / 3600, value=value, status=status, sent=False)
        if value is not None and B.send_full(radio, clock):
            acks.append((clock.s / 3600, value, t_meas))
            cyc["sent"] = True
        cycles.append(cyc)
        awake += clock.s - a0
        nxt = clock.s + SLEEP_S
        if resets and resets[0] * 3600 <= nxt:
            nxt = resets.pop(0) * 3600 + 30
            if logic == "V4" and flash is not None:
                ref = dict(value=flash, valid=True, cycles=2, rej=0, dz=0)
            else:
                ref = fresh()
        clock.s = nxt
    return acks, cycles, awake


def metrics(acks, cycles, world):
    m = B.metrics(acks, cycles, 0.0, world)
    sa = sorted(acks)
    ta = [a[0] for a in sa]
    longest = cur = 0
    for h in range(2, int(world.H)):
        i = bisect.bisect_right(ta, h) - 1
        bad = i < 0 or abs(sa[i][1] - max(world.truth(h), MIN_V)) > TOL
        cur = cur + 1 if bad else 0
        longest = max(longest, cur)
    m["longest_bad_h"] = longest
    m["fdz"] = sum(1 for a in acks if a[1] == MIN_V and world.truth(a[2]) >= FALSE_DZ_TRUTH)
    return m


def one(args):
    idx, variant, seed = args
    spec = SCN[idx]
    w = build_world(spec, seed)
    fault = Fault(spec, random.Random(seed * 1000003 + idx * 97 + 5), w)
    acks, cycles, awake = drive(w, seed, fault, variant)
    return idx, variant, metrics(acks, cycles, w)


# ======================= AGREGACJA / RAPORT =======================
def agg(ms):
    n = len(ms)
    avg = lambda k: sum(m[k] for m in ms) / n
    longs = sorted(m["longest_bad_h"] for m in ms)
    pump_vals = [x for m in ms for x in m["pump"] if x is not None]
    return dict(
        good=avg("good"),
        wrong_n=avg("wrong_n"),
        big_n=avg("big_n"),
        p_big=100.0 * sum(1 for m in ms if m["big_n"] > 0) / n,
        fdz=avg("fdz"),
        long_med=longs[n // 2],
        long_p95=longs[min(n - 1, int(0.95 * n))],
        long_max=longs[-1],
        stale=avg("stale"),
    )


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    jobs = [(i, v, s) for i in range(len(SCN)) for v in ("V3", "V4") for s in range(1, runs + 1)]
    with Pool() as p:
        res = p.map(one, jobs, chunksize=8)
    by = {}
    for i, v, m in res:
        by.setdefault((i, v), []).append(m)

    print(f"Przebiegow na scenariusz i wariant: {runs}  (50 dni, 100 cykli 12 h)")
    print("| Scenariusz | dobry % V3 / V4 | gruby blad szt. V3 / V4 | P(>=1 gruby) % V3 / V4 | "
          "falszywe 25.0 szt. V3 / V4 | blokada najdl. [h] med / max V3 | blokada med / max V4 |")
    print("|---|---|---|---|---|---|---|")
    for i, spec in enumerate(SCN):
        a3, a4 = agg(by[(i, "V3")]), agg(by[(i, "V4")])
        print(f"| {spec['name']} | {a3['good']:.1f} / {a4['good']:.1f} | "
              f"{a3['big_n']:.2f} / {a4['big_n']:.2f} | {a3['p_big']:.0f} / {a4['p_big']:.0f} | "
              f"{a3['fdz']:.2f} / {a4['fdz']:.2f} | {a3['long_med']} / {a3['long_max']} | "
              f"{a4['long_med']} / {a4['long_max']} |")


if __name__ == "__main__":
    main()
