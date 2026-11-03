"""Symulacja end-to-end: zbiornik -> czujnik -> TX (port firmware) -> radio -> RX (port firmware)."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "fw"))
sys.path.insert(0, HERE)

import protocol as P            # noqa: E402
import rx_logic as R            # noqa: E402
import rx_v2 as R2              # noqa: E402
import tx_main as T             # noqa: E402
from world import Tank, Sensor, Env, DAY  # noqa: E402


class Run:
    def __init__(self, seed=1, days=60, tank_kw=None, sensor_kw=None, env_kw=None,
                 tx_power_events=(), rx_boot_ms=0, rx_power_cycles=(), tx_first_wake=0.0, rx_manual_resets=(), v2=False, rtc_drift=0.0):
        self.rng = random.Random(seed)
        self.tank = Tank(random.Random(seed + 1), days=days + 5, **(tank_kw or {}))
        self.sensor = Sensor(self.tank, random.Random(seed + 2), **(sensor_kw or {}))
        self.env = Env(random.Random(seed + 3), **(env_kw or {}))
        self.v2 = v2
        self.rtc_drift = rtc_drift          # blad zegara RTC TX (+0.05 = sen trwa 5% dluzej niz zadany)
        self.rx = (R2.RxDevice2 if v2 else R.RxDevice)(boot_ms=rx_boot_ms)
        self.rxlog = P.RxTxLog()
        self.tx = T.TxDevice(self.sensor, self.env, self.rx, self.rxlog, seed=seed + 4, v2=v2)
        self.days = days
        self.tx_power_events = sorted(tx_power_events)      # (t, cut_at|None, corrupt_meta)
        self.rx_power_cycles = sorted(rx_power_cycles)      # (t_off, t_on)
        self.tx_first_wake = tx_first_wake
        self.rx_manual_resets = sorted(rx_manual_resets)      # momenty recznego RESET (przycisk) - po wywozie
        self.series = []         # (t, truth, rx_shown_raw|None, screen, led)
        self.fc = []             # (t, truth, (dni, kolor)|None) - prognoza 'Pelny za' pokazana na RX
        self.wakes = []
        self.rx_down_until = None

    def _rx_state_update(self, t):
        for (a, b) in self.rx_power_cycles:
            if a <= t < b:
                return False
        return True

    def run(self, step=600.0):
        t_end = self.days * DAY
        t = 0.0
        t_wake = self.tx_first_wake
        pend = list(self.tx_power_events)
        cur_ev = None
        rx_up_prev = True
        deliveries = []
        outage_edges = sorted({b for a, b in self.env.outages} | {b for a, b in self.rx_power_cycles})
        while t < t_end:
            # --- TX wake (zaplanowane lub zdarzenie zasilania) ---
            if pend and pend[0][0] <= t_wake and cur_ev is None:
                cur_ev = pend.pop(0)
                t_wake = cur_ev[0]
                self.tx.cold_boot()
            if t >= t_wake:
                ev, cur_ev = cur_ev, None
                cut = ev[1] if ev else None
                corrupt = ev[2] if ev else False
                info = self.tx.wake(t_wake, cut_at=cut, cut_corrupts_meta=corrupt)
                self.wakes.append(info)
                for ts, val, pl in info.get("deliveries", []):
                    deliveries.append((ts, val, pl))
                deliveries.sort()
                if info.get("cut"):
                    # po utracie zasilania w trakcie cyklu TX startuje od nowa po chwili (zasilanie wraca)
                    t_wake = t_wake + (cut or 0) + 5.0
                else:
                    t_wake = t_wake + info["active"] + info["sleep"] * (1.0 + self.rtc_drift)
                continue
            # --- RX: do nastepnego kroku ---
            t_next = min(t + step, t_wake, t_end)
            while self.rx_manual_resets and self.rx_manual_resets[0] <= t_next and self._rx_up(t_next):
                self.rx.manual_reset(self.rx_manual_resets.pop(0))
            # dostarczenia
            while deliveries and deliveries[0][0] <= t_next:
                ts, val, pl = deliveries.pop(0)
                if self._rx_up(ts):
                    if self.v2:
                        self.rx.on_packet2(max(ts, 0.0), val, pl)
                    else:
                        self.rx.on_packet(max(ts, 0.0), val)
            up = self._rx_up(t_next)
            if up and not rx_up_prev:
                self.rx.power_on(t_next)        # powrot zasilania RX: utrata RAM, NVS zostaje
                self.rxlog.reboot()
            rx_up_prev = up
            if up:
                self.rx.tick(t_next)
            t = t_next
            if t - (self.series[-1][0] if self.series else -1e9) >= step - 1e-6:
                self.series.append((t, self.tank.truth(t),
                                    None if not up else (self.rx.shown_cm() + 15 if self.rx.shown_cm() is not None else None),
                                    self.rx.screen if up else "off", self.rx.led(t) if up else "off"))
                self.fc.append((t, self.tank.truth(t), self.rx.forecast_state() if up else None))
        return self

    def _rx_up(self, t):
        for a, b in self.rx_power_cycles:
            if a <= t < b:
                return False
        return self.env.rx_up(t) if not self.env.outages else self.env.rx_up(t)
