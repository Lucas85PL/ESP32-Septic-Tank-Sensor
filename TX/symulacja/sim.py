#!/usr/bin/env python3
"""
Symulacja: stara logika (v1.5.0) vs nowa logika (v1.6.0) transmitera zbiornika.

Oba warianty to wierne porty kodu C++ (measurement.cpp + przeplyw z main.cpp) -
na tej maszynie nie ma kompilatora C++, wiec symulacja dziala na portach w Pythonie.
Ten sam swiat (poziom, wywozy, wyjecia czujnika, awarie odbiornika, serie bledow)
jest generowany z tego samego seeda dla obu wersji (porownanie sparowane).

Uruchomienie:  python sim.py            (pelna symulacja, kilka minut)
               python sim.py --quick    (mniej przebiegow)
"""
import bisect
import math
import random
import sys
from multiprocessing import Pool

# ======================= STALE (zgodne z config.h) =======================
MIN_VALID = 25.0
MAX_VALID = 170.0
SLEEP_S = 43200
INVALID = -1.0

# ---- stara logika (v1.5.0)
OLD_SERIES = 10
OLD_SERIES_INTERVAL_S = 60
OLD_FILL_SMALL = 5.0
OLD_FILL_LARGE = 15.0
OLD_FILL_RETRIES = 1
OLD_EMPTY_ZONE = 130.0
MAD_MULT = 3.0
MAD_CONST = 1.4826
MAD_MIN_RATIO = 0.5

# ---- nowa logika (v1.6.0)
NEW_SERIES = 6
NEW_SERIES_INTERVAL_S = 20
MAD_MIN_THRESHOLD = 1.0
MIN_SAMPLES = 5
CONS_TOL = 4.0
CONS_MIN_SERIES = 4
FILL_PER_DAY = 15.0
RISE_NOISE = 5.0
EMPTY_ZONE_NEW = 140.0
DEADZONE_CONFIRM = 3
MAX_REJECTED = 2
DEADZONE_PCT = 50
DEADZONE_LAST_MAX = 70.0
RETRY_SLEEP_S = 1800
RETRY_MAX = 3

SAMPLES = 10
SAMPLE_INTERVAL_S = 1.0
SAMPLE_COST_S = 0.03


# ======================= SWIAT =======================
class World:
    def __init__(self, sc, seed):
        r = random.Random(seed)
        self.sc = sc
        self.H = sc["days"]
        n = self.H + 5
        self.rates = [r.uniform(*sc["rate"]) for _ in range(n)]
        self.prefix = [0.0]
        for x in self.rates:
            self.prefix.append(self.prefix[-1] + x)
        d0 = r.uniform(100, 160)
        self.pumps = []
        self.seg_t = [0.0]
        self.seg_d = [d0]
        self.seg_c = [0.0]
        t = r.uniform(*sc["first_pump"])
        if sc["cap_full"]:
            t = min(t, self._until_level(0.0, d0, 0.0, 35.0))
        while t < self.H:
            self.pumps.append(t)
            d_after = r.uniform(158, 162)  # 3-7 cm cieczy po wywozie (dno 165 cm)
            self.seg_t.append(t)
            self.seg_d.append(d_after)
            self.seg_c.append(self._cum(t))
            nxt = t + r.uniform(*sc["pump_int"])
            if sc["cap_full"]:  # wywoz zanim zbiornik sie zapelni (odleglosc >= 35 cm)
                nxt = min(nxt, self._until_level(t, d_after, self._cum(t), 35.0))
            t = nxt
        # wyjecia czujnika (czas w godzinach)
        self.removals = []
        for tp in self.pumps:
            if tp < sc["event_end"] and r.random() < sc["remove_prob"]:
                dur = r.uniform(12, 24)
                start = tp * 24 - r.uniform(0.5, 4)
                mode = r.choice(["wall", "random", "timeout", "near"])
                par = {"wall": r.uniform(30, 150), "near": r.uniform(5, 24)}.get(mode, 0.0)
                self.removals.append((start, start + dur, mode, par))
        # awarie odbiornika (godziny)
        self.outages = []
        for dur in sc["outages"](r):
            start = r.uniform(8, sc["event_end"] - 10 - dur) * 24
            self.outages.append((start, start + dur * 24))
        # serie bledow pomiarowych (okna czasowe, godziny)
        self.bursts = []
        lam = sc["burst_per_day"]
        t = 0.0
        while lam > 0:
            t += r.expovariate(lam / 24.0)
            if t > self.H * 24:
                break
            self.bursts.append((t, t + r.uniform(2, 10) / 60.0))
        self.burst_starts = [b[0] for b in self.bursts]

    def _until_level(self, t0, d0, c0, target):
        t = t0
        while t < self.H + 60:
            if d0 - (self._cum(t) - c0) <= target:
                return t
            t += 0.05
        return self.H + 60

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
        for a, b in self.outages:
            if a <= th < b:
                return False
        return True

    def in_burst(self, th):
        i = bisect.bisect_right(self.burst_starts, th) - 1
        return i >= 0 and th < self.bursts[i][1]


class Clock:
    def __init__(self):
        self.s = 0.0

    def h(self):
        return self.s / 3600.0


class Sensor:
    def __init__(self, world, rng, clock):
        self.w, self.r, self.c = world, rng, clock
        self.p_out = world.sc["p_out"]

    def _outlier(self):
        return INVALID if self.r.random() < 0.5 else self.r.uniform(5, 200)

    def measure(self):
        th = self.c.h()
        self.c.s += SAMPLE_COST_S
        r = self.r
        rem = self.w.removal(th)
        if rem:
            mode, par = rem[2], rem[3]
            if mode == "wall":
                return par + r.gauss(0, 0.5)
            if mode == "random":
                return r.uniform(25, 170)
            if mode == "timeout":
                return INVALID
            return par + r.gauss(0, 0.5)  # near: lezy tuz przy podlozu (< 25 cm)
        if self.w.in_burst(th) and r.random() < 0.85:
            return r.uniform(25, 170) if r.random() < 0.85 else INVALID
        d = self.w.truth(th)
        if d < MIN_VALID:  # strefa martwa czujnika
            return r.uniform(15, 24.9) if r.random() < 0.7 else INVALID
        if r.random() < self.p_out:
            return self._outlier()
        return d + r.gauss(0, 0.4)


# ======================= POMOCNICZE =======================
def median(v):
    if not v:
        return INVALID
    s = sorted(v)
    n = len(s)
    return (s[n // 2 - 1] + s[n // 2]) / 2.0 if n % 2 == 0 else s[n // 2]


def mad_of(v, med):
    return median([abs(x - med) for x in v])


def valid_reading(d):
    return MIN_VALID <= d <= MAX_VALID


class Radio:
    """Model lacznosci: odbiornik niedostepny w oknach awarii + losowa utrata calej grupy prob."""

    def __init__(self, world, rng, clock):
        self.w, self.r, self.c = world, rng, clock
        self.p_fail = world.sc["p_group_fail"]

    def discover(self):
        up = self.w.rx_up(self.c.h())
        self.c.s += 1.0 if up else 10.0
        return up

    def send_group(self):  # sendDataWithRetry: 3 proby
        up = self.w.rx_up(self.c.h())
        if up and self.r.random() >= self.p_fail:
            self.c.s += 0.5
            return True
        self.c.s += 8.0
        return False


# ======================= STARA LOGIKA (port v1.5.0) =======================
class OldMeasurement:
    def __init__(self, sensor, clock, last, last_valid):
        self.s, self.c = sensor, clock
        self.last = last
        self.last_valid = last_valid

    def one_series(self):
        m = []
        for i in range(SAMPLES):
            d = self.s.measure()
            if valid_reading(d):
                m.append(d)
            if i < SAMPLES - 1:
                self.c.s += SAMPLE_INTERVAL_S
        return m

    def series_mad(self):
        m = self.one_series()
        if not m:
            return INVALID
        med = median(m)
        mad = mad_of(m, med)
        thr = MAD_MULT * MAD_CONST * mad
        f = [x for x in m if abs(x - med) <= thr]
        if len(f) / len(m) < MAD_MIN_RATIO:
            return med
        return median(f)

    def validate(self, cur):
        delta = cur - self.last
        if abs(delta) <= OLD_FILL_SMALL:
            return "ACCEPT"
        if delta > 0:
            return "SUSP_EMPTY" if cur >= OLD_EMPTY_ZONE else "IMPOSSIBLE_EMPTY"
        if abs(delta) > OLD_FILL_LARGE:
            return "SUSP_FILL"
        return "ACCEPT"

    def handle_fill(self):
        for _ in range(OLD_FILL_RETRIES):
            med = self.series_mad()
            if med == INVALID:
                continue
            delta = med - self.last
            if delta >= 0 or abs(delta) <= OLD_FILL_LARGE:
                return med, False
            self.c.s += 1.0
        return self.last, True

    def handle_empty(self):
        for _ in range(OLD_FILL_RETRIES):
            med = self.series_mad()
            if med == INVALID:
                continue
            if med - self.last > OLD_FILL_SMALL and med >= OLD_EMPTY_ZONE:
                return med, False
        return self.last, True

    def cycle(self):
        meds = []
        for series in range(OLD_SERIES):
            med = self.series_mad()
            if med == INVALID:
                continue
            if not self.last_valid:
                v = "ACCEPT"
                self.last_valid = True
            else:
                v = self.validate(med)
            if v == "IMPOSSIBLE_EMPTY":
                continue
            if v == "SUSP_FILL":
                res, fb = self.handle_fill()
                if fb:
                    continue
                med = res
            elif v == "SUSP_EMPTY":
                res, fb = self.handle_empty()
                if fb:
                    continue
                med = res
            meds.append(med)
            self.last = med
            if series < OLD_SERIES - 1:
                self.c.s += OLD_SERIES_INTERVAL_S
        if not meds:
            return None, 0
        return median(meds), len(meds)


def run_old(world, seed):
    clock = Clock()
    rng = random.Random(seed * 7919 + 1)
    sensor = Sensor(world, rng, clock)
    radio = Radio(world, rng, clock)
    last_accepted, last_valid = 100.0, False  # RTC
    slots = []
    clock.s = 0.1 * 3600
    end = world.H * 86400
    while clock.s < end:
        t_wake = clock.s
        awake0 = clock.s
        radio.discover()  # initializeEspNow -> discoverReceiver
        mm = OldMeasurement(sensor, clock, last_accepted, last_valid)
        value, n = mm.cycle()
        t_meas = clock.s
        slot = dict(t_wake=t_wake / 3600, t_meas=t_meas / 3600, value=value, n=n, sent=False,
                    t_ack=None, truth=world.truth(t_meas / 3600), rem=world.removal(t_wake / 3600) is not None,
                    rx=world.rx_up(t_wake / 3600), retry=False)
        if value is not None:
            ok = radio.send_group()
            if not ok:
                for _ in range(2):
                    if radio.discover():
                        if radio.send_group():
                            ok = True
                            break
                    clock.s += 1.0
            if ok:
                slot["sent"] = True
                slot["t_ack"] = clock.s / 3600
                last_accepted, last_valid = value, True  # tylko po ACK
        slot["awake"] = clock.s - awake0
        slots.append(slot)
        clock.s += SLEEP_S
    return slots


# ======================= NOWA LOGIKA (port v1.6.0) =======================
class NewMeasurement:
    def __init__(self, sensor, clock, ref):
        self.s, self.c, self.ref = sensor, clock, ref

    def series(self, st):
        m = []
        for i in range(SAMPLES):
            d = self.s.measure()
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
            if i < SAMPLES - 1:
                self.c.s += SAMPLE_INTERVAL_S
        if len(m) < MIN_SAMPLES:
            return INVALID
        med = median(m)
        thr = max(MAD_MULT * MAD_CONST * mad_of(m, med), MAD_MIN_THRESHOLD)
        f = [x for x in m if abs(x - med) <= thr]
        if len(f) / len(m) < MAD_MIN_RATIO:
            return med
        return median(f)

    def consensus(self, meds):
        if not meds:
            return False, INVALID, 0
        center = median(meds)
        agree = [x for x in meds if abs(x - center) <= CONS_TOL]
        return len(agree) >= CONS_MIN_SERIES, median(agree), len(agree)

    def within(self, v):
        days = (self.ref["cycles"] + 1) * (SLEEP_S / 86400.0)
        window = FILL_PER_DAY * days + RISE_NOISE
        delta = v - self.ref["value"]
        if delta > RISE_NOISE:
            return v >= EMPTY_ZONE_NEW
        return delta >= -window

    def accept(self, v):
        r = self.ref
        r["value"], r["valid"], r["cycles"], r["rejected"], r["dz"] = v, True, 0, 0, 0

    def cycle(self):
        st = dict(total=0, valid=0, below=0, above=0, timeouts=0)
        meds = []
        for s in range(NEW_SERIES):
            m = self.series(st)
            if m != INVALID:
                meds.append(m)
            if s < NEW_SERIES - 1:
                self.c.s += NEW_SERIES_INTERVAL_S
        ok, val, agree = self.consensus(meds)
        r = self.ref
        if not ok:
            if (st["below"] * 100 >= DEADZONE_PCT * st["total"] and r["valid"]
                    and r["value"] <= DEADZONE_LAST_MAX):
                if r["dz"] < DEADZONE_CONFIRM:
                    r["dz"] += 1
                if r["dz"] >= DEADZONE_CONFIRM:
                    self.accept(MIN_VALID)
                    r["dz"] = DEADZONE_CONFIRM
                    return MIN_VALID, CONS_MIN_SERIES, "DEADZONE"
                r["cycles"] += 1
                return None, 0, "NO_VALID"
            r["dz"] = 0
            r["cycles"] += 1
            return None, 0, "NO_VALID"
        if not r["valid"]:
            self.accept(val)
        elif self.within(val):
            self.accept(val)
        else:
            if r["rejected"] >= MAX_REJECTED:
                self.accept(val)
            else:
                r["rejected"] += 1
                r["dz"] = 0
                r["cycles"] += 1
                return None, agree, "JUMP_REJECTED"
        return val, agree, "OK"


def scaled(n):
    return (n * 10 + NEW_SERIES // 2) // NEW_SERIES


def run_new(world, seed):
    clock = Clock()
    rng = random.Random(seed * 7919 + 2)
    sensor = Sensor(world, rng, clock)
    radio = Radio(world, rng, clock)
    ref = dict(value=100.0, valid=False, cycles=0, rejected=0, dz=0)  # RTC
    pend = dict(on=False, value=0.0, retries=0, slot=None)  # RTC
    slots = []
    clock.s = 0.1 * 3600
    end = world.H * 86400

    def send_value():
        ok = radio.send_group()
        if not ok:
            for _ in range(2):
                if radio.discover():
                    if radio.send_group():
                        return True
                clock.s += 1.0
        return ok

    while clock.s < end:
        t_wake = clock.s
        awake0 = clock.s
        retry_wake = pend["on"]
        esp_ok = True
        radio.discover()
        sleep = SLEEP_S
        if retry_wake:
            slot = pend["slot"]
            ok = send_value()
            if ok:
                slot["sent"] = True
                slot["t_ack"] = clock.s / 3600
                sleep = SLEEP_S - pend["retries"] * RETRY_SLEEP_S
                pend.update(on=False, retries=0, slot=None)
            elif pend["retries"] < RETRY_MAX:
                pend["retries"] += 1
                sleep = RETRY_SLEEP_S
            else:
                sleep = SLEEP_S - pend["retries"] * RETRY_SLEEP_S
                pend.update(on=False, retries=0, slot=None)
            slot["awake"] += clock.s - awake0
        else:
            mm = NewMeasurement(sensor, clock, ref)
            value, n, status = mm.cycle()
            t_meas = clock.s
            slot = dict(t_wake=t_wake / 3600, t_meas=t_meas / 3600, value=value, n=n, sent=False,
                        t_ack=None, truth=world.truth(t_meas / 3600), status=status,
                        rem=world.removal(t_wake / 3600) is not None, rx=world.rx_up(t_wake / 3600),
                        retry=False)
            if value is not None:
                ok = send_value()
                if ok:
                    slot["sent"] = True
                    slot["t_ack"] = clock.s / 3600
                else:
                    pend.update(on=True, value=value, retries=1, slot=slot)
                    slot["retry"] = True
                    sleep = RETRY_SLEEP_S
            slot["awake"] = clock.s - awake0
            slots.append(slot)
        clock.s += sleep
    return slots


# ======================= METRYKI =======================
TOL = 8.0


def is_correct(s):
    return s["sent"] and abs(s["value"] - max(s["truth"], MIN_VALID)) <= TOL


def metrics(slots, world):
    H = world.H
    normal = [s for s in slots if not s["rem"] and s["rx"]]
    cor = sum(1 for s in normal if is_correct(s))
    wrong_n = sum(1 for s in normal if s["sent"] and not is_correct(s))
    silent_n = sum(1 for s in normal if not s["sent"])
    wrong_rem = sum(1 for s in slots if s["rem"] and s["sent"])  # fałszywe dane przy wyjetym czujniku
    wrong_all = sum(1 for s in slots if s["sent"] and not is_correct(s))
    last14 = [s for s in slots[-14:]]
    stuck_end = not any(is_correct(s) for s in last14)
    # dlugosc serii braku poprawnych danych (godziny, miedzy kolejnymi poprawnymi dostawami)
    ts = sorted([s["t_ack"] for s in slots if is_correct(s)])
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    if ts:
        gaps.append(H * 24 - ts[-1])
    max_gap = max(gaps) if gaps else H * 24
    # odzyskanie po awarii odbiornika / po wyjeciu czujnika
    def recover(t_end):
        c = [t for t in ts if t >= t_end]
        return (c[0] - t_end) if c else None

    rec_out = [recover(b) for a, b in world.outages]
    rec_rem = [recover(b) for (a, b, m, p) in world.removals]
    awake = sum(s["awake"] for s in slots) / 60.0 / H
    return dict(normal=len(normal), cor=cor, wrong_n=wrong_n, silent_n=silent_n, wrong_rem=wrong_rem,
                wrong_all=wrong_all, stuck=stuck_end, max_gap=max_gap, rec_out=rec_out, rec_rem=rec_rem,
                awake=awake, slots=len(slots))


# ======================= SCENARIUSZE =======================
def outages_none(r):
    return []


def outages_multi(r):
    return [r.choice([0.5, 1, 2, 3, 5, 7]) for _ in range(2)]


BASE = dict(days=120, event_end=100, rate=(5, 10), first_pump=(3, 25), pump_int=(18, 25),
            burst_per_day=0.3, p_out=0.02, remove_prob=0.0, outages=outages_none, p_group_fail=0.10,
            cap_full=True)

SCENARIOS = {
    "A. Bledy pomiarowe (umiarkowane) + wywozy": dict(BASE),
    "B. Bledy pomiarowe (ciezkie) + wywozy": dict(BASE, burst_per_day=2.0, p_out=0.08),
    "C. Wyjecie czujnika 12-24h przy kazdym wywozie": dict(BASE, remove_prob=1.0),
    "D. Brak odbiornika (2 awarie 0.5-7 dni)": dict(BASE, outages=outages_multi),
    "E. Zbiornik zapelniony do strefy martwej (wywoz co 32-38 dni)": dict(BASE, pump_int=(32, 38), cap_full=False),
    "F. Wszystko razem (ciezkie bledy + wyjecia + awarie)": dict(BASE, burst_per_day=2.0, p_out=0.08,
                                                              remove_prob=1.0, outages=outages_multi),
}


def one(args):
    name, seed = args
    sc = SCENARIOS[name]
    w = World(sc, seed)
    mo = metrics(run_old(w, seed), w)
    mn = metrics(run_new(w, seed), w)
    return name, mo, mn


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def pctl(v, p):
    v = sorted(v)
    if not v:
        return float("nan")
    return v[min(len(v) - 1, int(math.ceil(p / 100 * len(v))) - 1)]


def summarize(rows):
    n = len(rows)
    out = {}
    for ver in (0, 1):
        ms = [r[ver] for r in rows]
        d = {}
        d["stuck_pct"] = pct(sum(m["stuck"] for m in ms), n)
        d["cor_pct"] = pct(sum(m["cor"] for m in ms), sum(m["normal"] for m in ms))
        d["silent_pct"] = pct(sum(m["silent_n"] for m in ms), sum(m["normal"] for m in ms))
        d["wrong_n_per_run"] = sum(m["wrong_n"] for m in ms) / n
        d["wrong_rem_per_run"] = sum(m["wrong_rem"] for m in ms) / n
        d["gap_med_d"] = pctl([m["max_gap"] / 24 for m in ms], 50)
        d["gap_p95_d"] = pctl([m["max_gap"] / 24 for m in ms], 95)
        ro = [x for m in ms for x in m["rec_out"]]
        rr = [x for m in ms for x in m["rec_rem"]]
        d["rec_out_n"] = len(ro)
        d["rec_out_never"] = pct(sum(1 for x in ro if x is None), len(ro)) if ro else None
        okro = [x for x in ro if x is not None]
        d["rec_out_med_h"] = pctl(okro, 50) if okro else None
        d["rec_out_p95_h"] = pctl(okro, 95) if okro else None
        d["rec_rem_n"] = len(rr)
        d["rec_rem_never"] = pct(sum(1 for x in rr if x is None), len(rr)) if rr else None
        okrr = [x for x in rr if x is not None]
        d["rec_rem_med_h"] = pctl(okrr, 50) if okrr else None
        d["rec_rem_p95_h"] = pctl(okrr, 95) if okrr else None
        d["awake"] = sum(m["awake"] for m in ms) / n
        out[ver] = d
    return out


def f(x, fmt="{:.1f}"):
    return "-" if x is None else fmt.format(x)


def main():
    quick = "--quick" in sys.argv
    runs = 30 if quick else 100
    jobs = [(name, seed) for name in SCENARIOS for seed in range(1, runs + 1)]
    with Pool() as p:
        res = p.map(one, jobs, chunksize=4)
    by = {}
    for name, mo, mn in res:
        by.setdefault(name, []).append((mo, mn))

    lines = []
    lines.append(f"# Wyniki symulacji (przebiegow na scenariusz: {runs}, horyzont 120 dni, 2 pomiary/dobe)\n")
    lines.append("Tolerancja poprawnosci: dostarczona wartosc w +-8 cm od prawdy (strefa martwa: oczekiwane 25 cm).\n")
    for name, rows in by.items():
        s = summarize(rows)
        lines.append(f"\n## {name}\n")
        lines.append("| Metryka | STARA | NOWA |")
        lines.append("|---|---|---|")
        def row(label, key, fmt="{:.1f}"):
            lines.append(f"| {label} | {f(s[0][key], fmt)} | {f(s[1][key], fmt)} |")
        row("Przebiegi zablokowane na koncu (brak poprawnych danych w ostatnich 7 dniach) [%]", "stuck_pct")
        row("Normalne sloty (odbiornik OK, czujnik na miejscu): poprawnie dostarczone [%]", "cor_pct")
        row("Normalne sloty: cisza (brak wyslania) [%]", "silent_pct")
        row("Bledne dane wyslane w normalnych slotach [szt./przebieg]", "wrong_n_per_run", "{:.2f}")
        row("Bledne dane wyslane przy wyjetym czujniku [szt./przebieg]", "wrong_rem_per_run", "{:.2f}")
        row("Najdluzsza przerwa miedzy poprawnymi danymi - mediana [dni]", "gap_med_d")
        row("Najdluzsza przerwa miedzy poprawnymi danymi - p95 [dni]", "gap_p95_d")
        if s[0]["rec_out_n"]:
            row("Po awarii odbiornika: nigdy nie wrocil do poprawnych danych [%]", "rec_out_never")
            row("Po awarii odbiornika: czas do poprawnych danych - mediana [h]", "rec_out_med_h")
            row("Po awarii odbiornika: czas do poprawnych danych - p95 [h]", "rec_out_p95_h")
        if s[0]["rec_rem_n"]:
            row("Po wyjeciu czujnika: nigdy nie wrocil do poprawnych danych [%]", "rec_rem_never")
            row("Po wyjeciu czujnika: czas do poprawnych danych - mediana [h]", "rec_rem_med_h")
            row("Po wyjeciu czujnika: czas do poprawnych danych - p95 [h]", "rec_rem_p95_h")
        row("Czas aktywnosci (radio+czujnik) [min/dobe]", "awake")
    text = "\n".join(lines) + "\n"
    print(text)
    with open("wyniki.md", "w", encoding="utf-8") as fh:
        fh.write(text)


if __name__ == "__main__":
    main()
