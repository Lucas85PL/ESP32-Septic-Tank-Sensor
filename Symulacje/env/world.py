"""Swiat symulacji: zbiornik (fizyka), czujnik JSN-SR04T (szum, bledy, usterki), srodowisko radiowe."""
import math
import random

DAY = 86400.0


class Tank:
    """Odleglosc czujnik->powierzchnia [cm] jako funkcja czasu [s]. Napelnianie rate cm/dobe (zmienne),
    wywozy w zadanych momentach (poziom wraca do ~empty_cm)."""

    def __init__(self, rng, start_cm=120.0, rate=6.0, rate_var=0.3, pumpouts=(), empty_cm=160.0, days=120, floor=5.0):
        self.rng = rng
        self.pumpouts = sorted(pumpouts)
        self.step = 600.0
        n = int(days * DAY / self.step) + 2
        self.d = []
        level = start_cm
        r = rate
        pi = 0
        for k in range(n):
            t = k * self.step
            if k % 144 == 0:      # raz na dobe zmiana tempa
                r = max(0.0, rng.gauss(rate, rate * rate_var))
            while pi < len(self.pumpouts) and t >= self.pumpouts[pi]:
                level = empty_cm + rng.uniform(-3, 3)
                pi += 1
            level = max(floor, level - r * self.step / DAY)
            self.d.append(level)

    def truth(self, t):
        k = int(t / self.step)
        k = min(max(k, 0), len(self.d) - 2)
        f = (t - k * self.step) / self.step
        return self.d[k] * (1 - f) + self.d[k + 1] * f


class Sensor:
    """faults: lista dict(t0,t1,kind,...) w sekundach.
    kind: blind | echo(c,p) | random(p) | wall(c) | dead_stable(c)
    dz_mode: zachowanie przy prawdzie < 25 cm: 'scatter' (rozproszone 10-24 + timeouty), 'stable' (22 +-0.2), 'timeouts'"""

    def __init__(self, tank, rng, sigma=0.5, p_timeout=0.02, p_outlier=0.02, faults=(), dz_mode="scatter",
                 temp_c=20.0, assumed_c=20.0):
        self.tank, self.rng, self.sigma = tank, rng, sigma
        self.p_timeout, self.p_outlier = p_timeout, p_outlier
        self.faults = list(faults)
        self.dz_mode = dz_mode
        self.temp_c, self.assumed_c = temp_c, assumed_c
        self.powered = True
        self.reads = 0

    def _fault(self, t):
        for f in self.faults:
            if f["t0"] <= t < f["t1"]:
                return f
        return None

    def read(self, t):
        self.reads += 1
        rng = self.rng
        f = self._fault(t)
        truth = self.tank.truth(t)
        if f:
            k = f["kind"]
            if k == "blind":
                return -1.0
            if k == "below":                      # czujnik polozony tak, ze daje odczyty < 25 cm (strefa martwa)
                return rng.uniform(8, 24) if rng.random() < f.get("p", 0.8) else -1.0
            if k == "wall":
                return f["c"] + rng.gauss(0, 0.3)
            if k == "echo" and rng.random() < f.get("p", 1.0):
                return f["c"] + rng.gauss(0, 0.15)
            if k == "random" and rng.random() < f.get("p", 1.0):
                return rng.uniform(25, 170)
        if rng.random() < self.p_timeout:
            return -1.0
        if rng.random() < self.p_outlier:
            return rng.uniform(26, 168)
        # kompensacja temperatury: czujnik zakłada assumed_c, realnie temp_c
        scale = (331.3 + 0.606 * self.temp_c) / (331.3 + 0.606 * self.assumed_c)
        if truth < 25.0:
            if self.dz_mode == "stable":
                return 22.0 + rng.gauss(0, 0.2)
            if self.dz_mode == "timeouts":
                return -1.0
            return rng.uniform(10, 24) if rng.random() < 0.7 else -1.0
        return truth * scale + rng.gauss(0, self.sigma)


class Env:
    """srodowisko radiowe TX<->RX"""

    def __init__(self, rng, p_loss=0.0, outages=()):
        self.rng = rng
        self.p_loss = p_loss
        self.outages = list(outages)       # (t0,t1) RX wylaczony

    def rx_up(self, t):
        return not any(a <= t < b for a, b in self.outages)

    def lost(self):
        return self.rng.random() < self.p_loss
