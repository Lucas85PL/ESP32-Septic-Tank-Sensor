"""Port logiki RX 2.0.0 (po zmianach): main.cpp (czas 64-bitowy, alarm 25 h, dioda, NVS) + display.cpp
(historia, prognoza regresja liniowa, reset po wywozie) + espnow_receiver (przyjecie pakietu)."""
import math

SENSOR_HEIGHT_OFFSET = 10
MIN_DISTANCE = 15
MAX_DISTANCE = 145
HISTORY_SIZE = 14
EMPTY_THRESHOLD = 50
FORECAST_MIN_POINTS = 8
FORECAST_DEDUP_MS = 600_000
NO_DATA_TIMEOUT = 90_000_000
STATUS_ORANGE_AFTER_MS = 90_000_000
STATUS_RED_AFTER_MS = 180_000_000
SNAPSHOT_INTERVAL_MS = 3_600_000
MAX_AGE_SECONDS = 100_000_000
M32 = 0xFFFFFFFF


class RxDevice:
    def __init__(self, boot_ms=0):
        self.nvs = None                   # (raw, ageSeconds) - przezywa utrate zasilania
        self.boot_ms = boot_ms
        self.resets = 0
        self.power_on(0.0)

    def ms(self, t):
        """czas 64-bitowy (esp_timer) - bez zawijania"""
        return int(round((t - self.t_boot) * 1000)) + self.boot_ms

    def ms32(self, t):
        """millis() uint32 uzywany w display.cpp do znacznikow historii (roznice modulo 2^32)"""
        return self.ms(t) & M32

    def power_on(self, t):
        self.t_boot = t
        self.lastDistance = -1.0
        self.errorCount = 0
        self.sensorError = False
        self.reset_history()
        self.lastMeasurementMillis = 0
        self.lastTimeUpdateMillis = 0
        self.hasReceivedData = False
        self.warningShown = False
        self.lastValidMillis = 0
        self.lastValidRaw = 0.0
        self.hasValidMeasurement = False
        self.lastSnapshotMillis = 0
        self.screen = "waiting"
        if self.nvs is not None:
            raw, age = self.nvs
            age = min(age, MAX_AGE_SECONDS)
            now = self.ms(t)
            self.lastValidRaw = raw
            self.lastValidMillis = now - age * 1000
            self.lastMeasurementMillis = self.lastValidMillis
            self.lastTimeUpdateMillis = now
            self.lastSnapshotMillis = now
            self.hasValidMeasurement = True
            self.hasReceivedData = True
            self.lastDistance = raw - SENSOR_HEIGHT_OFFSET
            self.screen = "measure"
        self.rx_packets = []

    def manual_reset(self, t):
        """przycisk RESET (przytrzymanie 3 s): jak w main.cpp + display.performReset()"""
        self.nvs = None
        self.reset_history()
        self.lastDistance = -1.0
        self.errorCount = 0
        self.sensorError = False
        self.hasReceivedData = False
        self.warningShown = False
        self.hasValidMeasurement = False
        self.screen = "waiting"

    # ---- display.cpp: historia / prognoza ----
    def reset_history(self):
        self.hist = []                    # (ts32, dist) najnowszy na koncu
        self.lastDistanceForEmptyCheck = -1.0

    def add_to_history(self, dist, ts):
        if self.lastDistanceForEmptyCheck > 0 and dist > self.lastDistanceForEmptyCheck + EMPTY_THRESHOLD:
            self.reset_history()
            self.resets += 1
        self.lastDistanceForEmptyCheck = dist
        if self.hist and ((ts - self.hist[-1][0]) & M32) < FORECAST_DEDUP_MS:
            self.hist[-1] = (ts, dist)
            return
        self.hist.append((ts, dist))
        if len(self.hist) > HISTORY_SIZE:
            self.hist.pop(0)

    def forecast(self):
        """zwraca (lo, hi, open) albo None  (port forecastDays)"""
        n = len(self.hist)
        if n < FORECAST_MIN_POINTS:
            return None
        newest_ts, newest = self.hist[-1]
        xs = [-(((newest_ts - ts) & M32) / 3600000.0) for ts, _ in self.hist]
        ys = [d for _, d in self.hist]
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        syy = sum((y - my) ** 2 for y in ys)
        if sxx <= 1e-6:
            return None
        rate = -sxy / sxx
        if rate < 0.01:
            return None
        ssr = max(0.0, syy - sxy * sxy / sxx)
        se = math.sqrt(ssr / (n - 2) / sxx)
        dist_to_full = newest - MIN_DISTANCE
        if dist_to_full <= 0:
            return (0, 0, False)
        lo = int(math.floor(dist_to_full / (rate + se) / 24.0))
        opn = (rate - se) <= 0.005
        hi = lo if opn else max(lo, int(math.ceil(dist_to_full / (rate - se) / 24.0)))
        return (lo, hi, opn)

    def days_mid(self):
        """srodek zakresu prognozy w dniach albo -1"""
        f = self.forecast()
        if f is None:
            return -1
        lo, hi, opn = f
        return lo if opn else (lo + hi) / 2.0

    def forecast_state(self):
        """(dni_srodek, kolor) albo None - wspolny interfejs z RxDevice2"""
        d = self.days_mid()
        return None if d < 0 else (d, "green")

    def percent(self):
        if self.sensorError or self.lastDistance < 0:
            return 0
        p = (MAX_DISTANCE - self.lastDistance) / (MAX_DISTANCE - MIN_DISTANCE) * 100.0
        return int(min(100.0, max(0.0, p)))

    def show_measurement(self, raw, ts32):
        corrected = raw - SENSOR_HEIGHT_OFFSET
        valid = (raw >= 0 and raw <= (MAX_DISTANCE + SENSOR_HEIGHT_OFFSET) + 25)   # NaN -> False
        if valid:
            self.errorCount = 0
            self.sensorError = False
            self.lastDistance = corrected
            self.add_to_history(corrected, ts32)
        else:
            self.errorCount += 1
            if self.errorCount >= 6:
                self.sensorError = True
        self.screen = "measure"
        return valid

    def on_packet(self, t, raw):
        now = self.ms(t)
        valid = self.show_measurement(raw, self.ms32(t))
        self.lastMeasurementMillis = now
        self.lastTimeUpdateMillis = now
        self.hasReceivedData = True
        self.warningShown = False
        if valid:
            self.lastValidMillis = now
            self.lastValidRaw = raw
            self.hasValidMeasurement = True
            self.lastSnapshotMillis = now
            self.nvs = (raw, 0)
        self.rx_packets.append((t, raw))

    def tick(self, t):
        now = self.ms(t)
        if self.hasReceivedData and not self.warningShown:
            if now - self.lastMeasurementMillis >= NO_DATA_TIMEOUT:
                self.warningShown = True
                self.screen = "warning"
        if self.hasValidMeasurement:
            if now - self.lastSnapshotMillis >= SNAPSHOT_INTERVAL_MS:
                self.nvs = (self.lastValidRaw, max(0, min(MAX_AGE_SECONDS, (now - self.lastValidMillis) // 1000)))
                self.lastSnapshotMillis = now

    def led(self, t):
        if not self.hasValidMeasurement:
            return "none"
        age = self.ms(t) - self.lastValidMillis
        if age < STATUS_ORANGE_AFTER_MS:
            return "green"
        if age < STATUS_RED_AFTER_MS:
            return "orange"
        return "red"

    def shown_cm(self):
        return None if self.lastDistance < 0 else self.lastDistance
