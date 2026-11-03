#!/usr/bin/env python3
"""
Wariant A - 'anty-falszywe-echo'.

Uwaga: w katalogu symulacja/ NIE ma sim3.py ani NewLogic4/wyniki3.md (odniesienie V4 z prompt).
Dlatego ten plik jest samodzielny i bazuje tylko na istniejacym sim2.py (swiat, czujnik, radio,
metryki) oraz sim.py (stale). Logike V4 odtworzono z src/measurement.cpp + opisu z promptu
(wyjatek: wynik < 30 cm poza oknem nie resetuje odniesienia). Model bledu echa dolozono tutaj:
  - 'echo'      (40% przebiegow): 12-30 h, 25.4 cm w czesci probek (30-60%)
  - 'echo_long' (25% przebiegow): 60-84 h, 25.4 cm w 50-90% probek
  Echo dziala tylko gdy prawdziwy poziom >= 40 cm (falszywy 'pelny').
FAULTS=0 wylacza echo (kontrola regresji).

Uruchomienie: python swarm/anti_echo.py [liczba_przebiegow]   (domyslnie 150)
"""
import bisect
import os
import random
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sim as S  # noqa: E402
import sim2 as S2  # noqa: E402

FAULTS = int(os.environ.get("FAULTS", "1"))
MIN_VALID, MAX_VALID = 25.0, 170.0
SLEEP_S = 43200
ECHO_V = 25.4
RETRY = [1800, 1800, 1800, 3600, 3600, 7200, 7200]
FAKE_VALUE_MAX = 30.0   # dostarczona wartosc < 30 ...
FAKE_TRUTH_MIN = 40.0   # ... a prawda >= 40 => falszywy 'pelny'


# ======================= SWIAT Z ECHEM =======================
class World3(S2.World2):
    def __init__(self, seed):
        super().__init__(seed)
        r = random.Random(seed * 31 + 7)
        self.echoes = []
        if FAULTS:
            if r.random() < 0.40:
                s = r.uniform(0, 46 * 24)
                self.echoes.append((s, s + r.uniform(12, 30), r.uniform(0.30, 0.60)))
            if r.random() < 0.25:
                s = r.uniform(0, 44 * 24)
                self.echoes.append((s, s + r.uniform(60, 84), r.uniform(0.50, 0.90)))

    def echo_frac(self, th):
        for a, b, f in self.echoes:
            if a <= th < b:
                return f
        return 0.0


class Sensor3(S2.Sensor2):
    def measure(self):
        d = super().measure()
        f = self.w.echo_frac(self.c.h())
        if f > 0 and d >= 0 and self.r.random() < f:
            return ECHO_V + self.r.gauss(0, 0.25)
        return d


# ======================= LOGIKA (V4 + warianty A) =======================
BASE = dict(name="V4 (odtworzenie)", fill=15.0, glob_fill=None, low_cap=None, const=None, confirm=None,
            stag=None, boot=None, persist=True)  # persist: odniesienie we flash po resecie (jak firmware 1.4.8)


class Logic:
    def __init__(self, cfg):
        self.c = dict(BASE)
        self.c.update(cfg)

    # okno napelniania: 15 cm/dobe (lub zmniejszone tempo) * czas + 5 cm szumu
    def window(self, ref, cand):
        c = self.c
        days = (ref["cyc"] + 1) * (SLEEP_S / 86400.0)
        rate = c["glob_fill"] if c["glob_fill"] is not None else c["fill"]
        if c["low_cap"] is not None and cand < c["low_cap"][0]:
            rate = min(rate, c["low_cap"][1])
        return rate * days + 5.0

    def within(self, ref, v):
        delta = v - ref["value"]
        if delta > 5.0:
            return v >= 140.0                      # wywoz
        return delta >= -self.window(ref, v)       # napelnianie

    @staticmethod
    def accept(ref, v):
        ref.update(value=v, valid=True, cyc=0, rej=0, dz=0)

    @staticmethod
    def confirm(ref, v, need):
        """Wymaga 'need' kolejnych cykli z wartoscia +-3 cm. Zwraca True gdy potwierdzone."""
        p = ref.get("cpend")
        cnt = p[1] + 1 if (p and abs(p[0] - v) <= 3.0) else 1
        if cnt >= need:
            ref["cpend"] = None
            return True
        ref["cpend"] = (v, cnt)
        return False

    @staticmethod
    def clusters(pool):
        """Zachlanne okna 2*1.5 cm (jak firmware), do 3 klastrow. pool: lista (wartosc, seria)."""
        s = sorted(pool)
        out = []
        for _ in range(3):
            if not s:
                break
            vals = [x[0] for x in s]
            bi, bn = 0, 0
            for i in range(len(s)):
                j = bisect.bisect_right(vals, vals[i] + 3.0)
                if j - i > bn:
                    bi, bn = i, j - i
            seg = s[bi:bi + bn]
            vv = [x[0] for x in seg]
            out.append(dict(n=bn, med=S2.med(vv), lo=vv[0], hi=vv[-1]))
            s = s[:bi] + s[bi + bn:]
        return out

    def choose(self, cls, ref):
        good = [x for x in cls if x["n"] >= 12]     # POOL_MIN_SAMPLES
        if not good:
            return None
        if ref["valid"]:
            for x in good:
                if self.within(ref, x["med"]):
                    return x
        second = good[1]["n"] if len(good) > 1 else 0
        if good[0]["n"] >= 1.5 * second:            # POOL_DOMINANCE_RATIO
            return good[0]
        return None

    def no_value(self, ref, below, tot):
        ref["cpend"] = None
        if below * 100 >= 50 * tot and ref["valid"] and ref["value"] <= 70.0:
            ref["dz"] = min(ref["dz"] + 1, 3)
            if ref["dz"] >= 3:
                self.accept(ref, MIN_VALID)
                ref["dz"] = 3
                return MIN_VALID, "DEADZONE"
        else:
            ref["dz"] = 0
        ref["cyc"] += 1
        return None, "NO_VALID"

    def cycle(self, sensor, clock, ref):
        c = self.c
        sensor.begin_cycle(6)
        pool, tot, below, tmo = [], 0, 0, 0
        for s in range(6):
            for i in range(10):
                d = sensor.measure()
                tot += 1
                if d < 0:
                    tmo += 1
                elif d < MIN_VALID:
                    below += 1
                elif d <= MAX_VALID:
                    pool.append((d, s))
                if i < 9:
                    clock.s += 1.0
            if s < 5:
                clock.s += 20.0
        ch = self.choose(self.clusters(pool), ref) if pool else None
        if ch is None:
            return self.no_value(ref, below, tot)
        v = ch["med"]

        # A6: stagnacja w strefie niskiej - wartosc prawie identyczna z odniesieniem przez k cykli
        # (realne napelnianie 5-8 cm/dobe = 2.5-4 cm na cykl, wiec stagnacja <30 cm jest podejrzana)
        if c["stag"] is not None and ref["valid"]:
            k = c["stag"]
            if k["lo"] <= v < k["hi"] and abs(v - ref["value"]) <= k["tol"]:
                ref["stg"] = ref.get("stg", 0) + 1
            else:
                ref["stg"] = 0
            if ref["stg"] >= k["k"]:
                ref["cyc"] += 1
                return None, "NO_VALID"

        # A2: wasko skupiony klaster tuz nad minimum + duzo timeoutow => sygnatura falszywego echa
        if c["const"] is not None:
            k = c["const"]
            if 25.0 <= v < 35.0 and (ch["hi"] - ch["lo"]) <= k["spread"] and tmo >= k["tmo"] * tot:
                if not self.confirm(ref, v, k["n"]):
                    ref["cyc"] += 1
                    return None, "NO_VALID"

        if not ref["valid"]:
            # A9: bootstrap (brak odniesienia) przy niskiej wartosci wymaga potwierdzenia
            if c["boot"] is not None and v < 35.0:
                if not self.confirm(ref, v, c["boot"]):
                    ref["cyc"] += 1
                    return None, "NO_VALID"
            self.accept(ref, v)
            return v, "OK"

        # A3: duzy skok w dol w jednym cyklu wymaga potwierdzenia
        if c["confirm"] is not None:
            k = c["confirm"]
            if ref["value"] - v > k["cm"]:
                if not self.confirm(ref, v, k["n"]):
                    ref["cyc"] += 1
                    return None, "NO_VALID"
        ref["cpend"] = None

        if self.within(ref, v):
            self.accept(ref, v)
            return v, "OK"
        if v < FAKE_VALUE_MAX:                      # wyjatek V4: <30 cm poza oknem nigdy nie resetuje
            ref["rej"] += 1
            ref["dz"] = 0
            ref["cyc"] += 1
            return None, "JUMP_REJECTED"
        if ref["rej"] >= 2:
            self.accept(ref, v)
            return v, "OK"
        ref["rej"] += 1
        ref["dz"] = 0
        ref["cyc"] += 1
        return None, "JUMP_REJECTED"

    def run(self, world, seed):
        clock, rng = S2.Clock(), random.Random(seed * 7919 + 5)
        sensor, radio = Sensor3(world, rng, clock), S2.Radio2(world, rng, clock)
        fresh = lambda: dict(value=100.0, valid=False, cyc=0, rej=0, dz=0, cpend=None)
        ref = fresh()
        pend = None
        acks, cycles, awake = [], [], 0.0
        resets = list(world.resets)
        clock.s = 0.1 * 3600
        end = world.H * 3600
        next_reg = clock.s
        while clock.s < end:
            a0 = clock.s
            if pend is not None and clock.s < next_reg - 1:
                radio.discover()
                if world.rx_up(clock.s / 3600):      # swiezy pomiar przy ponowieniu
                    v2, _ = self.cycle(sensor, clock, ref)
                    if v2 is not None:
                        pend["value"], pend["t"] = v2, clock.s / 3600
                if S2.send_full(radio, clock):
                    acks.append((clock.s / 3600, pend["value"], pend["t"]))
                    pend = None
                    nxt = next_reg
                else:
                    pend["k"] += 1
                    if pend["k"] <= len(RETRY):
                        nxt = min(clock.s + RETRY[pend["k"] - 1], next_reg)
                    else:
                        pend = None
                        nxt = next_reg
            else:
                pend = None
                radio.discover()
                value, status = self.cycle(sensor, clock, ref)
                t_meas = clock.s / 3600
                cyc = dict(t=a0 / 3600, value=value, status=status, sent=False)
                nxt = clock.s + SLEEP_S
                next_reg = nxt
                if value is not None:
                    if S2.send_full(radio, clock):
                        acks.append((clock.s / 3600, value, t_meas))
                        cyc["sent"] = True
                    else:
                        pend = dict(value=value, t=t_meas, k=1)
                        nxt = clock.s + RETRY[0]
                cycles.append(cyc)
            awake += clock.s - a0
            if resets and resets[0] * 3600 <= nxt:
                nxt = resets.pop(0) * 3600 + 30
                pend = None
                if self.c["persist"] and ref["valid"]:
                    # odtworzenie z flash: okno jak po 2 dodatkowych cyklach (REF_RESTORE_EXTRA_CYCLES)
                    ref.update(cyc=ref["cyc"] + 2, rej=0, dz=0, cpend=None, stg=0)
                else:
                    ref = fresh()
                next_reg = nxt
            clock.s = nxt
        return acks, cycles, awake


# ======================= WARIANTY =======================
VARIANTS = {}


def reg(name, **cfg):
    cfg["name"] = name
    VARIANTS[name] = Logic(cfg)


reg("V4 (odtworzenie)")
reg("A1l cap 8/d gdy <40", low_cap=(40.0, 8.0))
reg("A1g cap 8/d globalnie", glob_fill=8.0)
reg("A2 guard stale-min", const=dict(spread=0.8, tmo=0.4, n=2))
reg("A3 potwierdz skok>10 x3", confirm=dict(cm=10.0, n=3))
reg("A4 = A1l+A2+A3", low_cap=(40.0, 8.0), const=dict(spread=0.8, tmo=0.4, n=2),
    confirm=dict(cm=10.0, n=3))
reg("A5 = A1g+A3", glob_fill=8.0, confirm=dict(cm=10.0, n=3))
reg("A6a stagnacja <35 k=1", stag=dict(lo=25.0, hi=35.0, tol=1.0, k=1))
reg("A6b stagnacja <35 k=2", stag=dict(lo=25.0, hi=35.0, tol=1.0, k=2))
reg("A7 = A6a+A3", stag=dict(lo=25.0, hi=35.0, tol=1.0, k=1), confirm=dict(cm=10.0, n=3))
reg("A8 = A6a+A3+A2(bez tmo)", stag=dict(lo=25.0, hi=35.0, tol=1.0, k=1),
    confirm=dict(cm=10.0, n=3), const=dict(spread=1.5, tmo=0.0, n=2))
reg("A9 = A6a+A3+boot2", stag=dict(lo=25.0, hi=35.0, tol=1.0, k=1),
    confirm=dict(cm=10.0, n=3), boot=2)
reg("A10 = A6a+A1l+boot2", stag=dict(lo=25.0, hi=35.0, tol=1.0, k=1),
    low_cap=(40.0, 8.0), boot=2)


# ======================= METRYKI I URUCHOMIENIE =======================
def metrics(acks, cycles, awake, world):
    m = S2.metrics(acks, cycles, awake, world)
    acks_s = sorted(acks)
    t_ack = [a[0] for a in acks_s]

    def view(t):
        i = bisect.bisect_right(t_ack, t) - 1
        return acks_s[i] if i >= 0 else None

    fake_h = 0
    for h in range(2, int(world.H)):
        v = view(h)
        if v is not None and v[1] < FAKE_VALUE_MAX and world.truth(h) >= FAKE_TRUTH_MIN:
            fake_h += 1
    fake_n = sum(1 for a in acks if a[1] < FAKE_VALUE_MAX and world.truth(a[2]) >= FAKE_TRUTH_MIN)
    m["fake_n"] = fake_n
    m["fake_view"] = 100.0 * fake_h / max(1, int(world.H) - 2)
    return m


def one(args):
    name, seed = args
    w = World3(seed)
    acks, cycles, awake = VARIANTS[name].run(w, seed)
    return name, metrics(acks, cycles, awake, w)


def summarize(ms):
    n = len(ms)
    avg = lambda k: sum(m[k] for m in ms) / n
    return dict(good=avg("good"), stale=avg("stale"), wrong=avg("wrong"), big=avg("big_n"),
                mae=avg("mae"), deliv=avg("deliv"), fake_n=avg("fake_n"),
                fake_runs=100.0 * sum(1 for m in ms if m["fake_n"] > 0) / n,
                fake_view=avg("fake_view"), awake=avg("awake"))


def table(res, order):
    L = ["| Wariant | Widok DOBRY % | NIEAKTUALNY % | BLEDNY % | Grube bledy /50d | MAE cm | "
         "Falszywy pelny: przebiegi % | Falszywy pelny: dostawy /50d | Falszywy pelny: % czasu | Dostawy /50d | min/dobe |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for nm in order:
        r = res[nm]
        L.append(f"| {nm} | {r['good']:.1f} | {r['stale']:.1f} | {r['wrong']:.1f} | {r['big']:.2f} | "
                 f"{r['mae']:.1f} | {r['fake_runs']:.1f} | {r['fake_n']:.2f} | {r['fake_view']:.2f} | "
                 f"{r['deliv']:.1f} | {r['awake']:.1f} |")
    return "\n".join(L)


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    names = list(VARIANTS)
    jobs = [(nm, seed) for nm in names for seed in range(1, runs + 1)]
    with Pool() as p:
        out = p.map(one, jobs, chunksize=4)
    by = {}
    for nm, m in out:
        by.setdefault(nm, []).append(m)
    res = {nm: summarize(ms) for nm, ms in by.items()}
    print(f"FAULTS={FAULTS} runs={runs}")
    print(table(res, names))
