#!/usr/bin/env python3
"""
Symulacja 2: iteracyjne szukanie lepszej logiki. Start: logika TX 1.4.7 (v1.6.0).

Scenariusz (50 dni, 100 cykli po 12 h):
 - start na pustym zbiorniku (7 cm cieczy, dno 165 cm => 158 cm odleglosci)
 - dzienny przyrost 5-8 cm (losowy, osobno na kazda dobe)
 - w kazdej serii 10-60% pomiarow z bledami (losowo na serie)
 - w kazdym cyklu 10-50% serii "odrzuconych" (kompletnie zepsutych; 1-5 z 10 proporcjonalnie do liczby serii)
 - 2 awarie zasilania odbiornika: jedna na 1 pomiar (12 h), druga na 2 pomiary (24 h)
 - 2 wyjecia czujnika (12-24 h, dziwne odczyty np. "pelny") dokladnie w czasie 2 wywozow (ok. dzien 19 i ok. 40)
 - 2 resety zasilania nadajnika TX

Uruchomienie:  python sim2.py [liczba_przebiegow]   (domyslnie 300)
"""
import bisect
import math
import os
import random
import sys
from multiprocessing import Pool

import sim as S  # port starej logiki (v1.5.0) i stale

MIN_VALID, MAX_VALID, SLEEP_S = 25.0, 170.0, 43200
DAYS = 50
ERR_LO, ERR_HI = float(os.environ.get("ERR_LO", 0.10)), float(os.environ.get("ERR_HI", 0.60))
BAD_LO, BAD_HI = float(os.environ.get("BAD_LO", 0.10)), float(os.environ.get("BAD_HI", 0.50))
TOL_GOOD = 10.0     # widok odbiornika "dobry", gdy |wartosc - prawda| <= 10 cm
STALE_H = 26.0      # starsze niz 26 h = "nieaktualny"
BAD_ERR = 8.0       # dostarczona wartosc bledna, gdy |blad| > 8 cm
BIG_ERR = 20.0


# ======================= SWIAT =======================
class World2:
    def __init__(self, seed):
        r = random.Random(seed)
        self.H = DAYS * 24.0
        self.rates = [r.uniform(5, 8) for _ in range(DAYS + 3)]
        self.prefix = [0.0]
        for x in self.rates:
            self.prefix.append(self.prefix[-1] + x)
        p1 = 19 + r.uniform(-1.5, 1.5)
        p2 = p1 + 21 + r.uniform(-1.5, 1.5)
        self.pumps = [p1, p2]  # dni
        self.seg_t, self.seg_d, self.seg_c = [0.0], [158.0], [0.0]
        for tp in self.pumps:
            self.seg_t.append(tp)
            self.seg_d.append(165.0 - r.uniform(3, 7))
            self.seg_c.append(self._cum(tp))
        # wyjecia czujnika wokol wywozow (godziny)
        self.removals = []
        for tp in self.pumps:
            start = tp * 24 - r.uniform(1, 5)
            dur = r.uniform(12, 24)
            u = r.random()
            if u < 0.5:
                mode, par = "full", r.uniform(5, 24)       # odczyty "pelny" (< 25 cm)
            elif u < 0.75:
                mode, par = "random", 0.0
            else:
                mode, par = "wall", r.uniform(30, 150)
            self.removals.append((start, start + dur, mode, par))
        # awarie odbiornika: 12 h i 24 h
        while True:
            s1 = r.uniform(2 * 24, 46 * 24)
            s2 = r.uniform(2 * 24, 45 * 24)
            if abs(s1 - s2) > 48:
                break
        self.outages = [(s1, s1 + 12), (s2, s2 + 24)]
        # resety zasilania TX (godziny)
        while True:
            a = r.uniform(3 * 24, 47 * 24)
            b = r.uniform(3 * 24, 47 * 24)
            if abs(a - b) > 72:
                break
        self.resets = sorted([a, b])

    def _cum(self, td):
        k = min(int(td), len(self.rates) - 1)
        return self.prefix[k] + self.rates[k] * (td - k)

    def truth(self, th):
        td = th / 24.0
        i = bisect.bisect_right(self.seg_t, td) - 1
        return max(8.0, self.seg_d[i] - (self._cum(td) - self.seg_c[i]))

    def removal(self, th):
        for r in self.removals:
            if r[0] <= th < r[1]:
                return r
        return None

    def rx_up(self, th):
        return not any(a <= th < b for a, b in self.outages)


class Clock:
    def __init__(self):
        self.s = 0.0

    def h(self):
        return self.s / 3600.0


class Sensor2:
    """Czujnik: bledy per seria (10-60% probek) + per cykl 10-50% serii calkowicie zepsutych."""

    def __init__(self, world, rng, clock):
        self.w, self.r, self.c = world, rng, clock
        self.idx, self.last_t, self.pfrac, self.cnt = -1, -1e9, 0.3, 0
        self.bad = {}
        self.n_series = 10

    def begin_cycle(self, n_series):
        r = self.r
        self.n_series = n_series
        q = r.uniform(BAD_LO, BAD_HI)
        k = max(1, round(q * n_series))
        self.bad = {}
        for i in r.sample(range(n_series), k):
            # zepsuta seria: losowy rozrzut albo stabilna zla wartosc
            self.bad[i] = ("rand", 0.0) if r.random() < 0.5 else ("stable", r.uniform(30, 150))
        self.idx, self.last_t, self.cnt = -1, -1e9, 0

    def measure(self):
        t = self.c.s
        r = self.r
        if t - self.last_t > 5.0 or self.cnt >= S.SAMPLES:  # nowa seria
            self.idx += 1
            self.cnt = 0
            self.pfrac = r.uniform(ERR_LO, ERR_HI)
        self.cnt += 1
        self.last_t = t
        self.c.s += S.SAMPLE_COST_S
        th = self.c.h()
        rem = self.w.removal(th)
        if rem:
            mode, par = rem[2], rem[3]
            if mode == "wall":
                return par + r.gauss(0, 0.5)
            if mode == "random":
                return r.uniform(25, 170) if r.random() < 0.85 else -1.0
            return par + r.gauss(0, 0.5)  # "full": < 25 cm
        if self.idx in self.bad:
            kind, c = self.bad[self.idx]
            if kind == "rand":
                return r.uniform(25, 170) if r.random() < 0.9 else -1.0
            return (c + r.gauss(0, 0.5)) if r.random() < 0.8 else r.uniform(25, 170)
        d = self.w.truth(th)
        if d < MIN_VALID:
            return r.uniform(15, 24.9) if r.random() < 0.7 else -1.0
        if r.random() < self.pfrac:  # blad pojedynczej probki
            return -1.0 if r.random() < 0.5 else r.uniform(5, 200)
        return d + r.gauss(0, 0.4)


class Radio2:
    def __init__(self, world, rng, clock, p_fail=0.02):
        self.w, self.r, self.c, self.p = world, rng, clock, p_fail

    def discover(self):
        up = self.w.rx_up(self.c.h())
        self.c.s += 1.0 if up else 10.0
        return up

    def send_group(self):
        up = self.w.rx_up(self.c.h())
        if up and self.r.random() >= self.p:
            self.c.s += 0.5
            return True
        self.c.s += 8.0
        return False


def send_full(radio, clock):
    ok = radio.send_group()
    if not ok:
        for _ in range(2):
            if radio.discover() and radio.send_group():
                return True
            clock.s += 1.0
    return ok


# ======================= STARA LOGIKA (1.4.5 / v1.5.0) =======================
def run_old(world, seed):
    clock, rng = Clock(), random.Random(seed * 7919 + 1)
    sensor, radio = Sensor2(world, rng, clock), Radio2(world, rng, clock)
    last, valid = 100.0, False
    acks, cycles, awake = [], [], 0.0
    resets = list(world.resets)
    clock.s = 0.1 * 3600
    end = world.H * 3600
    while clock.s < end:
        a0 = clock.s
        sensor.begin_cycle(S.OLD_SERIES)
        radio.discover()
        mm = S.OldMeasurement(sensor, clock, last, valid)
        value, n = mm.cycle()
        t_meas = clock.s / 3600
        cyc = dict(t=a0 / 3600, value=value, status="OK" if value is not None else "NO_VALID", sent=False)
        if value is not None and send_full(radio, clock):
            acks.append((clock.s / 3600, value, t_meas))
            cyc["sent"] = True
            last, valid = value, True
        cycles.append(cyc)
        awake += clock.s - a0
        nxt = clock.s + SLEEP_S
        if resets and resets[0] * 3600 <= nxt:
            nxt = resets.pop(0) * 3600 + 30
            last, valid = 100.0, False
        clock.s = nxt
    return acks, cycles, awake


# ======================= NOWA LOGIKA (parametryzowana) =======================
V0 = dict(  # TX 1.4.7 = v1.6.0
    name="V0 (TX 1.4.7)", n_series=6, int_s=20, min_samples=5, cons="series", tol=4.0, min_series=4,
    fill_day=15.0, noise=5.0, empty_zone=140.0, max_rej=2, dz_cycles=3, dz_last=70.0,
    retry=[1800, 1800, 1800], persist=False, prior=False,
)


def med(v):
    return S.median(v)


class NewLogic:
    def __init__(self, cfg):
        self.cfg = cfg

    # ---- jedna seria (MAD) ----
    def series(self, sensor, clock, st, collect):
        c = self.cfg
        m = []
        for i in range(S.SAMPLES):
            d = sensor.measure()
            st["total"] += 1
            if d < 0:
                st["timeouts"] += 1
            elif d < MIN_VALID:
                st["below"] += 1
            elif d > MAX_VALID:
                st["above"] += 1
            else:
                st["valid"] += 1
                m.append(d)
                collect.append(d)
            if i < S.SAMPLES - 1:
                clock.s += 1.0
        if len(m) < c["min_samples"]:
            return None
        mm = med(m)
        thr = max(3.0 * 1.4826 * S.mad_of(m, mm), 1.0)
        f = [x for x in m if abs(x - mm) <= thr]
        if len(f) / len(m) < 0.5:
            return mm
        return med(f)

    # ---- konsensus ----
    def cons_series(self, meds):
        c = self.cfg
        if not meds:
            return None
        ctr = med(meds)
        agree = [x for x in meds if abs(x - ctr) <= c["tol"]]
        if len(agree) >= c["min_series"]:
            return med(agree), len(agree)
        return None

    def clusters(self, samples):
        """Najgestsze okna +-pool_half na probkach (zachlanne, do 3 klastrow)."""
        c = self.cfg
        s = sorted(samples)
        out = []
        w = 2 * c.get("pool_half", 2.0)
        for _ in range(3):
            if not s:
                break
            best_i, best_n = 0, 0
            for i in range(len(s)):
                j = bisect.bisect_right(s, s[i] + w)
                if j - i > best_n:
                    best_i, best_n = i, j - i
            cl = s[best_i:best_i + best_n]
            out.append((best_n, med(cl)))
            s = s[:best_i] + s[best_i + best_n:]
        return out

    # ---- walidacja miedzy cyklami ----
    def within(self, ref, v):
        c = self.cfg
        days = (ref["cycles"] + 1) * (c.get("sleep_s", SLEEP_S) / 86400.0)
        window = c["fill_day"] * days + c["noise"]
        delta = v - ref["value"]
        if delta > c["noise"]:
            return v >= c["empty_zone"]
        return delta >= -window

    def accept(self, ref, v):
        ref.update(value=v, valid=True, cycles=0, rej=0, dz=0)

    def cycle(self, sensor, clock, ref):
        c = self.cfg
        sensor.begin_cycle(c["n_series"])
        st = dict(total=0, valid=0, below=0, above=0, timeouts=0)
        meds, pool = [], []
        for s in range(c["n_series"]):
            m = self.series(sensor, clock, st, pool)
            if m is not None:
                meds.append(m)
            if s < c["n_series"] - 1:
                clock.s += c["int_s"]
        res = None
        if c["cons"] == "series":
            res = self.cons_series(meds)
            agree = res[1] if res else 0
            val = res[0] if res else None
        else:
            val, agree = self.cons_pool(pool, st, ref)
        if val is None:
            if (st["below"] * 100 >= 50 * st["total"] and ref["valid"] and ref["value"] <= c["dz_last"]):
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
        elif ref["rej"] >= c["max_rej"]:
            self.accept(ref, val)
        else:
            ref["rej"] += 1
            ref["dz"] = 0
            ref["cycles"] += 1
            return None, "JUMP_REJECTED"
        return val, "OK"

    def cons_pool(self, pool, st, ref):
        """Konsensus na poziomie probek: najgestszy klaster wszystkich poprawnych probek cyklu.
        prior=True: sposrod klastrow wybierz najwiekszy ZGODNY z oczekiwanym zakresem (okno czasowe/wywoz)."""
        c = self.cfg
        cl = self.clusters(pool)
        cl = [x for x in cl if x[0] >= c["pool_min"]]
        if not cl:
            return None, 0
        if c["prior"] and ref["valid"]:
            ok = [x for x in cl if self.within(ref, x[1])]
            if ok:
                return ok[0][1], ok[0][0]
        top = cl[0]
        second = cl[1][0] if len(cl) > 1 else 0
        if top[0] >= c["pool_ratio"] * second:
            return top[1], top[0]
        return None, 0

    # ---- caly przebieg ----
    def run(self, world, seed):
        c = self.cfg
        clock, rng = Clock(), random.Random(seed * 7919 + 2)
        sensor, radio = Sensor2(world, rng, clock), Radio2(world, rng, clock)
        fresh = lambda: dict(value=100.0, valid=False, cycles=0, rej=0, dz=0)
        ref = fresh()
        pend = None  # dict(value, t_meas, k, due)
        acks, cycles, awake = [], [], 0.0
        resets = list(world.resets)
        clock.s = 0.1 * 3600
        end = world.H * 3600
        next_reg = clock.s
        while clock.s < end:
            a0 = clock.s
            if pend is not None and clock.s < next_reg - 1:
                # watek retry
                radio.discover()
                if c.get("remeasure") and world.rx_up(clock.s / 3600):
                    v2, _st = self.cycle(sensor, clock, ref)  # swiezy pomiar zamiast starej wartosci
                    if v2 is not None:
                        pend["value"], pend["t_meas"] = v2, clock.s / 3600
                if send_full(radio, clock):
                    acks.append((clock.s / 3600, pend["value"], pend["t_meas"]))
                    pend = None
                    nxt = next_reg
                else:
                    pend["k"] += 1
                    if pend["k"] <= len(c["retry"]):
                        nxt = min(clock.s + c["retry"][pend["k"] - 1], next_reg)
                    else:
                        pend = None
                        nxt = next_reg
            else:
                pend = None
                radio.discover()
                value, status = self.cycle(sensor, clock, ref)
                t_meas = clock.s / 3600
                cyc = dict(t=a0 / 3600, value=value, status=status, sent=False)
                nxt = clock.s + c.get("sleep_s", SLEEP_S)
                next_reg = nxt
                if value is not None:
                    if send_full(radio, clock):
                        acks.append((clock.s / 3600, value, t_meas))
                        cyc["sent"] = True
                    elif c["retry"]:
                        pend = dict(value=value, t_meas=t_meas, k=1)
                        nxt = clock.s + c["retry"][0]
                cycles.append(cyc)
            awake += clock.s - a0
            if resets and resets[0] * 3600 <= nxt:
                nxt = resets.pop(0) * 3600 + 30
                pend = None
                if c["persist"] and ref["valid"]:
                    ref["cycles"] += 1  # RTC skasowane, ref odtworzony z flash
                    ref["rej"] = ref["dz"] = 0
                else:
                    ref = fresh()
                next_reg = nxt
            clock.s = nxt
        return acks, cycles, awake


# ======================= SUFIT: IDEALNY CZUJNIK =======================
def run_oracle(world, seed, sleep_s=SLEEP_S):
    """Idealny pomiar (prawda + szum) w tych samych cyklach 12 h, ta sama lacznosc, bez retry."""
    clock, rng = Clock(), random.Random(seed * 7919 + 3)
    radio = Radio2(world, rng, clock)
    acks, cycles, awake = [], [], 0.0
    clock.s = 0.1 * 3600
    while clock.s < world.H * 3600:
        a0 = clock.s
        t_meas = clock.s / 3600 + 0.05
        v = world.truth(t_meas) + rng.gauss(0, 0.4)
        v = max(v, MIN_VALID)
        ok = send_full(radio, clock)
        if ok:
            acks.append((clock.s / 3600, v, t_meas))
        cycles.append(dict(t=a0 / 3600, value=v, status="OK", sent=ok))
        awake += 160
        clock.s += sleep_s
    return acks, cycles, awake


# ======================= METRYKI =======================
def metrics(acks, cycles, awake, world):
    H = world.H
    acks = sorted(acks)
    t_ack = [a[0] for a in acks]

    def view(t):
        i = bisect.bisect_right(t_ack, t) - 1
        return acks[i] if i >= 0 else None

    good = stale = wrong = blind = 0
    abs_err = []
    for h in range(2, int(H)):
        v = view(h)
        if v is None:
            blind += 1
            continue
        err = abs(v[1] - max(world.truth(h), MIN_VALID))
        if err <= TOL_GOOD:
            good += 1
        elif h - v[0] > STALE_H:
            stale += 1
        else:
            wrong += 1
        abs_err.append(min(err, 100))
    n = good + stale + wrong + blind
    wrongd = [a for a in acks if abs(a[1] - max(world.truth(a[2]), MIN_VALID)) > BAD_ERR]
    bigd = [a for a in wrongd if abs(a[1] - max(world.truth(a[2]), MIN_VALID)) > BIG_ERR]

    def first_good_after(t0):
        for a in acks:
            if a[2] >= t0 and abs(a[1] - max(world.truth(a[2]), MIN_VALID)) <= BAD_ERR:
                return a[0] - t0
        return None

    pump_delay = [first_good_after(p * 24) for p in world.pumps]
    reset_rec = [first_good_after(r) for r in world.resets]
    out_rec = [first_good_after(b) for a, b in world.outages]
    return dict(good=100 * good / n, stale=100 * stale / n, wrong=100 * wrong / n, blind=100 * blind / n,
                mae=sum(abs_err) / len(abs_err) if abs_err else 100.0,
                wrong_n=len(wrongd), big_n=len(bigd), deliv=len(acks),
                pump=pump_delay, reset=reset_rec, outage=out_rec,
                awake=awake / 60.0 / DAYS,
                statuses={s: sum(1 for c in cycles if c["status"] == s) for s in
                          ("OK", "NO_VALID", "JUMP_REJECTED", "DEADZONE")})


# ======================= URUCHOMIENIE =======================
VARIANTS = {}


def register(name, fn):
    VARIANTS[name] = fn


def one(args):
    name, seed = args
    w = World2(seed)
    acks, cycles, awake = VARIANTS[name](w, seed)
    return name, metrics(acks, cycles, awake, w)


def pct(v, p):
    v = sorted(x for x in v)
    return v[min(len(v) - 1, int(math.ceil(p / 100 * len(v))) - 1)] if v else float("nan")


def summarize(ms):
    n = len(ms)
    avg = lambda k: sum(m[k] for m in ms) / n

    def hours(key):
        vals = [x for m in ms for x in m[key]]
        ok = [x for x in vals if x is not None]
        never = 100 * (len(vals) - len(ok)) / len(vals) if vals else 0
        return (pct(ok, 50) if ok else float("nan"), pct(ok, 95) if ok else float("nan"), never)

    sts = {s: sum(m["statuses"][s] for m in ms) / n for s in ("OK", "NO_VALID", "JUMP_REJECTED", "DEADZONE")}
    return dict(good=avg("good"), stale=avg("stale"), wrong=avg("wrong"), blind=avg("blind"), mae=avg("mae"),
                wrong_n=avg("wrong_n"), big_n=avg("big_n"), deliv=avg("deliv"), awake=avg("awake"),
                pump=hours("pump"), reset=hours("reset"), outage=hours("outage"), sts=sts,
                worst_big=max(m["big_n"] for m in ms))


def table(results, order):
    cols = [(k, results[k]) for k in order]
    L = []
    L.append("| Metryka | " + " | ".join(k for k, _ in cols) + " |")
    L.append("|---|" + "---|" * len(cols))

    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(fn(r) for _, r in cols) + " |")

    row("Widok odbiornika DOBRY (blad <= 10 cm) [% czasu]", lambda r: f"{r['good']:.1f}")
    row("Widok NIEAKTUALNY (brak swiezych danych > 26 h) [%]", lambda r: f"{r['stale']:.1f}")
    row("Widok BLEDNY (swieze, ale zle dane) [%]", lambda r: f"{r['wrong']:.1f}")
    row("Sredni blad widoku [cm]", lambda r: f"{r['mae']:.1f}")
    row("Dostarczone bledne wartosci (> 8 cm) [szt./50 dni]", lambda r: f"{r['wrong_n']:.2f}")
    row("w tym grube bledy (> 20 cm) [szt./50 dni]", lambda r: f"{r['big_n']:.2f}")
    row("Dostarczone wartosci ogolem [szt./50 dni]", lambda r: f"{r['deliv']:.1f}")
    row("Wykrycie wywozu: mediana / p95 [h] (nie wykryto %)",
        lambda r: f"{r['pump'][0]:.1f} / {r['pump'][1]:.1f} ({r['pump'][2]:.0f}%)")
    row("Powrot po resecie TX: mediana / p95 [h] (nie wrocil %)",
        lambda r: f"{r['reset'][0]:.1f} / {r['reset'][1]:.1f} ({r['reset'][2]:.0f}%)")
    row("Powrot po awarii odbiornika: mediana / p95 [h] (nie wrocil %)",
        lambda r: f"{r['outage'][0]:.1f} / {r['outage'][1]:.1f} ({r['outage'][2]:.0f}%)")
    row("Cykle: OK / NO_VALID / JUMP_REJ / DEADZONE",
        lambda r: f"{r['sts']['OK']:.0f} / {r['sts']['NO_VALID']:.0f} / {r['sts']['JUMP_REJECTED']:.0f} / {r['sts']['DEADZONE']:.0f}")
    row("Czas aktywnosci [min/dobe]", lambda r: f"{r['awake']:.1f}")
    return "\n".join(L)


def run_all(names, runs):
    jobs = [(nm, seed) for nm in names for seed in range(1, runs + 1)]
    with Pool() as p:
        res = p.map(one, jobs, chunksize=8)
    by = {}
    for nm, m in res:
        by.setdefault(nm, []).append(m)
    return {nm: summarize(ms) for nm, ms in by.items()}


# ======================= ITERACJE =======================
V1 = dict(V0, name="V1 klastry probek", cons="pool", pool_half=2.0, pool_min=12, pool_ratio=1.5)

CONFIGS = [V0, V1]

register("SUFIT (idealny czujnik)", run_oracle)
register("1.4.5 (v1.5.0)", run_old)
for _cfg in CONFIGS:
    register(_cfg["name"], (lambda cfg: (lambda w, s: NewLogic(cfg).run(w, s)))(_cfg))

if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    names = list(VARIANTS)
    results = run_all(names, runs)
    print(table(results, names))
