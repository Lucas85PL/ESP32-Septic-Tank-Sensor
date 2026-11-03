"""RX v2 (propozycja): historia przychodzi W PAKIECIE z TX (do 14 zatwierdzonych punktow z wiekiem), RX jej nie zbiera sam.
 - odcinanie po RESET przyciskiem: (epoka, seq) zapisane w NVS -> punkty z seq <= N ignorowane
 - blob historii w NVS (odtwarzany po utracie zasilania RX z wiekiem z snapshotu)
 - zabezpieczenie: skok odleglosci w gore > EMPTY_THRESHOLD w odebranej historii odcina starsze punkty
 - prognoza: do 36 h danych 'prior' 6 cm/dobe (kolor pomaranczowy), potem regresja (zielony)
Sztuczne 25.0 cm (strefa martwa) nie wchodzi do regresji."""
import math

import rx_logic as R

FORECAST_PRIOR_RATE_CM_PER_DAY = 6.0
FORECAST_MIN_POINTS_V2 = 7          # 7 punktow co 6 h = 36 h
FORECAST_MIN_SPAN_H = 35.0          # tolerancja na jitter cyklu


class RxDevice2(R.RxDevice):
    def __init__(self, boot_ms=0):
        self.nvs2 = None                 # dict(epoch, seq, pts=[(raw, wiek_wzgl_najnowszego_s, synth)]) - przezywa utrate zasilania
        self.cut = None                  # (epoka, seq) - po RESET przyciskiem; przezywa utrate zasilania
        super().__init__(boot_ms)

    # ---- zycie urzadzenia ----
    def reset_history(self):
        super().reset_history()
        self.pts = []                    # [(ts_ms64, dist_corrected, synth)] najstarszy pierwszy
        self.lastepoch = None
        self.lastseq = None

    def power_on(self, t):
        super().power_on(t)
        if self.nvs is not None and self.nvs2 is not None:
            h = self.nvs2
            self.lastepoch, self.lastseq = h["epoch"], h["seq"]
            newest_ts = self.lastValidMillis        # wiek najnowszego punktu = wiek z snapshotu (jak ostatni pomiar)
            self.pts = sorted(((newest_ts - age * 1000, raw - R.SENSOR_HEIGHT_OFFSET, syn) for raw, age, syn in h["pts"]),
                              key=lambda p: p[0])

    def manual_reset(self, t):
        ep, sq = self.lastepoch, self.lastseq
        if sq is None and self.nvs2 is not None:
            ep, sq = self.nvs2["epoch"], self.nvs2["seq"]
        super().manual_reset(t)
        if sq is not None:
            self.cut = (ep, sq)
        self.nvs2 = None

    # ---- odbior pakietu ----
    def on_packet2(self, t, raw, payload):
        if payload is None:                          # pakiet bez historii (np. TX nie zdazyl jej zbudowac)
            return self.on_packet(t, raw)
        epoch, seq, pts = payload["epoch"], payload["seq"], payload["pts"]       # pts: najnowszy pierwszy
        if self.cut and self.cut[0] == epoch and seq <= self.cut[1]:
            return                                   # stary pakiet sprzed RESET-u
        if self.lastepoch == epoch and self.lastseq is not None and seq < self.lastseq:
            return                                   # opozniony / stary duplikat
        if self.cut and self.cut[0] == epoch:
            pts = [p for i, p in enumerate(pts) if seq - i > self.cut[1]]
        if self.cut and self.cut[0] != epoch:
            self.cut = None
        # zabezpieczenie: skok w gore (wywoz) w historii -> tylko punkty po nim
        keep = len(pts)
        for j in range(len(pts) - 1):
            if pts[j][0] - pts[j + 1][0] > R.EMPTY_THRESHOLD:
                keep = j + 1
                break
        pts = pts[:keep]
        now = self.ms(t)
        self.pts = sorted(((now - age * 1000, v - R.SENSOR_HEIGHT_OFFSET, syn) for v, age, syn in pts), key=lambda p: p[0])
        self.lastepoch, self.lastseq = epoch, seq
        newest_raw = pts[0][0]
        valid = newest_raw >= 0 and newest_raw <= (R.MAX_DISTANCE + R.SENSOR_HEIGHT_OFFSET) + 25
        if valid:
            self.errorCount = 0
            self.sensorError = False
            self.lastDistance = newest_raw - R.SENSOR_HEIGHT_OFFSET
        else:
            self.errorCount += 1
            if self.errorCount >= 6:
                self.sensorError = True
        self.screen = "measure"
        self.lastMeasurementMillis = now
        self.lastTimeUpdateMillis = now
        self.hasReceivedData = True
        self.warningShown = False
        if valid:
            self.lastValidMillis = now
            self.lastValidRaw = newest_raw
            self.hasValidMeasurement = True
            self.lastSnapshotMillis = now
            self.nvs = (newest_raw, 0)
            newest_age = 0
            self.nvs2 = dict(epoch=epoch, seq=seq, pts=[(v, a, s) for v, a, s in pts])
        self.rx_packets.append((t, raw))

    # ---- prognoza ----
    def forecast(self):
        f = self.forecast2()
        return None if f is None else f[:3]

    def forecast2(self):
        """(lo, hi, open, kolor) albo None"""
        if not self.pts:
            return None
        real = [p for p in self.pts if not p[2]]
        newest = self.pts[-1][1]
        dist_to_full = newest - R.MIN_DISTANCE
        if dist_to_full <= 0:
            return (0, 0, False, "green")
        n = len(real)
        span_h = (real[-1][0] - real[0][0]) / 3600000.0 if n >= 2 else 0.0
        if n >= FORECAST_MIN_POINTS_V2 and span_h >= FORECAST_MIN_SPAN_H:
            xs = [(ts - real[-1][0]) / 3600000.0 for ts, _, _ in real]
            ys = [d for _, d, _ in real]
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
            lo = int(math.floor(dist_to_full / (rate + se) / 24.0))
            opn = (rate - se) <= 0.005
            hi = lo if opn else max(lo, int(math.ceil(dist_to_full / (rate - se) / 24.0)))
            return (lo, hi, opn, "green")
        days = int(round(dist_to_full / FORECAST_PRIOR_RATE_CM_PER_DAY))
        return (days, days, False, "orange")

    def forecast_state(self):
        f = self.forecast2()
        if f is None:
            return None
        lo, hi, opn, col = f
        return ((lo if opn else (lo + hi) / 2.0), col)
