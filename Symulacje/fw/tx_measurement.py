"""Wierny port TX 2.0.0 src/measurement.cpp + stale z config.h (logika klastrow V3/v1.7.2).
Port 1:1 - te same progi, te same galezie. Kazda zmiana firmware wymaga aktualizacji tego pliku."""
import math
from dataclasses import dataclass, field

# --- config.h ---
SERIES_COUNT = 6
MEAS_PER_SERIES = 10
SERIES_INTERVAL_S = 20
MEAS_INTERVAL_S = 1
MIN_VALID = 25.0
MAX_VALID = 170.0
POOL_HALF_WIDTH = 1.5
POOL_MIN_SAMPLES = 12
POOL_DOMINANCE_RATIO = 1.5
POOL_MAX_CLUSTERS = 3
POOL_PRIOR_MIN_SAMPLES = 6
POOL_PRIOR_MIN_SERIES = 3
POOL_SERIES_MIN_SAMPLES = 3
FILL_MAX_CM_PER_DAY = 15.0
RISE_NOISE = 5.0
SLOW_FILL = 8.0
SLOW_ZONE = 10.0
EMPTY_ZONE_MIN = 140.0
MAX_REJECTED = 4
NEAR_MIN_MARGIN = 5.0
DZ_RATIO_PCT = 50
DZ_LAST_MAX = 70.0
DZ_REPORTED_SERIES = 4
DZ_PLAUS_MARGIN = 5.0
DZ_MIN_SPREAD = 1.5
DZ_CONFIRM = 6
FIRST_CYCLE_FALLBACK = 100.0
RISE_CONFIRM_TOL = 10.0

OK, BELOW_MIN_RANGE, NO_VALID, REJECTED_JUMP = "OK", "BELOW_MIN_RANGE", "NO_VALID", "REJECTED_JUMP"


@dataclass
class RefState:
    value: float = FIRST_CYCLE_FALLBACK
    valid: bool = False
    secondsSinceRef: int = 0
    rejectedCycles: int = 0
    deadzoneCycles: int = 0
    risePending: int = 0
    riseValue: float = 0.0

    def copy(self):
        return RefState(self.value, self.valid, self.secondsSinceRef, self.rejectedCycles, self.deadzoneCycles,
                        self.risePending, self.riseValue)


@dataclass
class Result:
    value: float = -1.0
    isValid: bool = False
    status: str = NO_VALID
    acceptedSeriesCount: int = 0
    log: list = field(default_factory=list)


def median(vals):
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return -1.0
    return (v[n // 2 - 1] + v[n // 2]) / 2.0 if n % 2 == 0 else v[n // 2]


class MeasurementManager:
    """sensor_read() -> cm (<0 = timeout); delay(sec) przesuwa zegar symulacji."""

    def __init__(self, sensor_read, delay, ref: RefState, is_retry=False, accept_rise_now=False):
        self.read, self.delay, self.ref, self.is_retry = sensor_read, delay, ref, is_retry
        self.accept_rise_now = accept_rise_now
        self.notes = []

    # --- klastry ---
    def find_clusters(self, samples):
        samples = sorted(samples, key=lambda s: s[0])
        width = 2.0 * POOL_HALF_WIDTH
        clusters = []
        for _ in range(POOL_MAX_CLUSTERS):
            if not samples:
                break
            best_start, best_count = 0, 0
            for i in range(len(samples)):
                j = i
                while j < len(samples) and samples[j][0] <= samples[i][0] + width:
                    j += 1
                if j - i > best_count:
                    best_start, best_count = i, j - i
            chunk = samples[best_start:best_start + best_count]
            clusters.append(dict(count=best_count, lo=chunk[0][0], hi=chunk[-1][0],
                                 median=median([c[0] for c in chunk]),
                                 series=len({c[1] for c in chunk})))
            del samples[best_start:best_start + best_count]
        return clusters

    def fill_window(self, rate):
        return rate * (self.ref.secondsSinceRef / 86400.0) + RISE_NOISE

    def within_allowed(self, value):
        rate = SLOW_FILL if value < MIN_VALID + SLOW_ZONE else FILL_MAX_CM_PER_DAY
        window = self.fill_window(rate)
        delta = value - self.ref.value
        if delta > RISE_NOISE:
            return value >= EMPTY_ZONE_MIN
        return delta >= -window

    def accept(self, value):
        r = self.ref
        r.value, r.valid, r.secondsSinceRef, r.rejectedCycles, r.deadzoneCycles = value, True, 0, 0, 0
        r.risePending = 0

    def evaluate(self, pool):
        if not pool:
            return None
        allc = self.find_clusters(list(pool))
        clusters = [c for c in allc if c["count"] >= POOL_MIN_SAMPLES]
        chosen = None
        if self.ref.valid:
            for c in allc:
                if c["count"] >= POOL_PRIOR_MIN_SAMPLES and c["series"] >= POOL_PRIOR_MIN_SERIES \
                        and self.within_allowed(c["median"]):
                    chosen = c
                    break
        if chosen is None and not clusters:
            return None
        if chosen is None:
            top = clusters[0]
            second = clusters[1]["count"] if len(clusters) > 1 else 0
            if top["count"] >= POOL_DOMINANCE_RATIO * second:
                chosen = top
        if chosen is None:
            return None
        per = [0] * SERIES_COUNT
        for v, s in pool:
            if chosen["lo"] <= v <= chosen["hi"]:
                per[s] += 1
        agreeing = sum(1 for p in per if p >= POOL_SERIES_MIN_SAMPLES)
        return chosen["median"], agreeing

    def run_cycle(self):
        ref = self.ref
        res = Result()
        pool, total, valid, below, above, tmo = [], 0, 0, 0, 0, 0
        bsum = bsq = 0.0
        for s in range(SERIES_COUNT):
            for i in range(MEAS_PER_SERIES):
                d = self.read()
                total += 1
                if d < 0:
                    tmo += 1
                elif d < MIN_VALID:
                    below += 1
                    bsum += d
                    bsq += d * d
                elif d > MAX_VALID:
                    above += 1
                else:
                    valid += 1
                    pool.append((d, s))
                if i < MEAS_PER_SERIES - 1:
                    self.delay(MEAS_INTERVAL_S)
            if s < SERIES_COUNT - 1:
                self.delay(SERIES_INTERVAL_S)

        cons = self.evaluate(pool)
        if cons is None:
            mostly_below = total > 0 and below * 100 >= DZ_RATIO_PCT * total
            dz_window = self.fill_window(SLOW_FILL)
            plausible = ref.valid and (ref.value - dz_window) <= MIN_VALID + DZ_PLAUS_MARGIN
            spread = 0.0
            if below > 1:
                mean = bsum / below
                var = bsq / below - mean * mean
                spread = math.sqrt(var) if var > 0 else 0.0
            spread_ok = spread >= DZ_MIN_SPREAD
            if mostly_below and plausible and spread_ok and ref.value <= DZ_LAST_MAX:
                if not self.is_retry and ref.deadzoneCycles < DZ_CONFIRM:
                    ref.deadzoneCycles += 1
                if ref.deadzoneCycles >= DZ_CONFIRM:
                    self.accept(MIN_VALID)
                    ref.deadzoneCycles = DZ_CONFIRM
                    res.value, res.isValid, res.status, res.acceptedSeriesCount = MIN_VALID, True, BELOW_MIN_RANGE, DZ_REPORTED_SERIES
                    return res
                res.status = NO_VALID
                return res
            ref.deadzoneCycles = 0
            res.status = NO_VALID
            return res

        value, agreeing = cons
        res.acceptedSeriesCount = agreeing
        if not ref.valid:
            self.accept(value)
        elif self.within_allowed(value):
            if value - ref.value > RISE_NOISE and not self.accept_rise_now:
                # wywoz: potwierdzenie w 2 kolejnych cyklach (retry nie potwierdza i nie ustawia kandydata)
                if not self.is_retry and ref.risePending and abs(value - ref.riseValue) <= RISE_CONFIRM_TOL:
                    self.accept(value)
                else:
                    if not self.is_retry:
                        ref.risePending, ref.riseValue = 1, value
                    ref.deadzoneCycles = 0
                    res.status = REJECTED_JUMP
                    return res
            else:
                self.accept(value)
        else:
            if value < MIN_VALID + NEAR_MIN_MARGIN:
                ref.deadzoneCycles = 0
                res.status = NO_VALID
                return res
            if not self.is_retry and ref.rejectedCycles >= MAX_REJECTED:
                self.accept(value)
            else:
                if not self.is_retry:
                    ref.rejectedCycles += 1
                ref.deadzoneCycles = 0
                res.status = REJECTED_JUMP
                return res
        res.value, res.isValid, res.status = value, True, OK
        return res
