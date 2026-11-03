"""Port TX 2.0.0 main.cpp::setup() (maszyna stanow cyklu, ponowienia, plan snu) + espnow_manager (czasy/wynik)
+ ref_store + event_logger (commit). Jedno wywolanie wake() = jedno wybudzenie z deep sleep."""
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tx_measurement as M
import protocol as P

DEEP_SLEEP_SECONDS = 21600
SEND_RETRY_SCHEDULE_S = [1800, 1800, 1800, 3600, 3600, 7200, 7200]
SEND_RETRY_COUNT = 7
SEND_RETRY_MARGIN_S = 120
FAILED_CYCLES_NO_RETRY = 1
REF_RESTORE_EXTRA_SECONDS = 86400
ESPNOW_MAX_RETRIES = 3
DISCOVERY_TIMEOUT = 10.0
HIST_POINTS = 14                 # v2: punktow historii w pakiecie
HIST_ASSUMED_GAP_S = 10800       # v2: po resecie TX wiek najnowszego punktu nieznany -> zakladamy pol okresu (3 h)


class PowerCut(Exception):
    pass


class Rtc:
    def __init__(self):
        self.ref = M.RefState()
        self.pendingSend = False
        self.pendingValue = 0.0
        self.pendingSeries = 0
        self.pendingRetryIdx = 0
        self.secondsToRegular = 0
        self.elapsedSincePrevWake = 0
        self.failedRegular = 0           # kolejne regularne cykle zakonczone brakiem ACK (po serii ponowien)
        self.hist = None                 # v2: [[value, ts_believed_s, synth]] (None = do odtworzenia z flash)
        self.hclock = 0                  # v2: czas TX liczony z zadanych snow [s]
        self.cur_pt = False              # v2: ostatni punkt pochodzi z biezacego cyklu (ponowienie go zastepuje)


class Radio:
    """port espnow_manager: zwraca czasy i skutki. deliveries -> lista (t_abs, value) pakietow, ktore DOTARLY do RX."""

    def __init__(self, env, rxdev, rx_txlog, rng, t_base, clk, cut=None):
        self.env, self.rxdev, self.rx_txlog, self.rng = env, rxdev, rx_txlog, rng
        self.t_base, self.clk = t_base, clk
        self.known = False
        self.last_known = False       # _lastKnownMac ustawiony
        self.initialized = False
        self.packet_id = 0
        self.deliveries = []
        self.wifi_s = 0.0
        self._wifi_since = None
        self.stats = dict(discover_fail=0, discover_ok=0, send_fail=0)

    def now(self):
        return self.t_base + self.clk["t"]

    def adv(self, dt):
        self.clk["t"] += dt

    def begin(self):
        self.initialized = True
        self._wifi_since = self.clk["t"]
        self.adv(0.15)
        return True

    def shutdown(self):
        if self.known:
            self.last_known = True
        if self._wifi_since is not None:
            self.wifi_s += self.clk["t"] - self._wifi_since
            self._wifi_since = None
        self.initialized = False
        self.known = False

    def close(self):
        if self._wifi_since is not None:
            self.wifi_s += self.clk["t"] - self._wifi_since
            self._wifi_since = None

    def discover(self):
        if not self.initialized:
            return False
        if self.known:
            self.last_known = True
        self.known = False
        t_start = self.clk["t"]
        env = self.env
        for k in range(2):                       # broadcast co 5 s w oknie 10 s
            if env.rx_up(self.now() + 5.0 * k) and not env.lost() and not env.lost():
                self.adv(0.05 + 5.0 * k)
                self.known = True
                self.stats["discover_ok"] += 1
                return True
        self.adv(10.0)
        self.stats["discover_fail"] += 1
        return False

    def send_data(self, value, payload=None):
        """jedna proba sendData(): (sukces_ack, dotarl_do_rx)"""
        if not self.known:
            return False
        env = self.env
        up = env.rx_up(self.now())
        data_ok = up and not env.lost()
        if data_ok:
            self.deliveries.append((self.now() + 0.02, value, payload))
        ack_ok = data_ok and not env.lost()
        self.adv(0.06 if ack_ok else (0.2 if not up else 2.0))
        return ack_ok

    def send_with_retry(self, value, payload=None):
        for attempt in range(1, ESPNOW_MAX_RETRIES + 1):
            self.packet_id += 1
            if self.send_data(value, payload):
                return True
            if attempt < ESPNOW_MAX_RETRIES:
                self.adv(1.0)
        self.stats["send_fail"] += 1
        return False


class TxDevice:
    def __init__(self, tank_sensor, env, rxdev, rx_txlog, seed=1, v2=False):
        self.v2 = v2                       # v2: historia pomiarow w TX + pakiet z historia
        self.sensor = tank_sensor
        self.env, self.rxdev, self.rx_txlog = env, rxdev, rx_txlog
        self.rng = random.Random(seed)
        self.rtc = Rtc()
        self.store = P.TxStore(self.rng)
        self.store.hist2 = None            # flash: dict(epoch, seq, pts=[(value, wiek wzgl. najnowszego, synth)])
        self.cycle_no = 0
        self._sensor_on = 0.0
        self.manual_boot = True              # pierwsze wlaczenie = reset reczny
        self.log = []                      # (t, dict) podsumowania wybudzen
        self.energy = dict(sensor_s=0.0, wifi_s=0.0, active_s=0.0, wakes=0)

    def cold_boot(self):
        """utrata zasilania / przycisk EN: RTC zerowane, flash zostaje; pierwszy cykl przyjmuje wywoz bez potwierdzenia"""
        self.rtc = Rtc()
        self.manual_boot = True

    # ------------------------------------------------------------------
    def wake(self, t_wake, cut_at=None, cut_corrupts_meta=False):
        clk = {"t": 0.0}
        rtc = self.rtc
        store = self.store
        info = dict(t=t_wake, kind="regular", meas=None, sendOk=None, sleep=None)

        def adv(dt):
            clk["t"] += dt
            if cut_at is not None and clk["t"] >= cut_at:
                raise PowerCut()

        sensor_off_at = [None]
        radio = Radio(self.env, self.rxdev, self.rx_txlog, self.rng, t_wake, clk)
        radio.adv = adv                          # zegar z mozliwoscia odciecia zasilania
        try:
            return self._wake(t_wake, clk, adv, radio, info, sensor_off_at)
        except PowerCut:
            if cut_corrupts_meta:
                store.meta = None
            radio.close()
            self.energy["wifi_s"] += radio.wifi_s
            self.energy["sensor_s"] += (sensor_off_at[0] if sensor_off_at[0] is not None else clk["t"]) - self._sensor_on
            self.energy["active_s"] += clk["t"]
            self.cold_boot()
            info["cut"] = True
            return info

    def _wake(self, t_wake, clk, adv, radio, info, sensor_off_at):
        rtc, store = self.rtc, self.store
        adv(0.7)                                # boot + Serial + mount LittleFS
        store.begin()
        if rtc.ref.valid:
            rtc.ref.secondsSinceRef += rtc.elapsedSincePrevWake
        rtc.hclock += rtc.elapsedSincePrevWake
        rtc.elapsedSincePrevWake = 0
        if self.v2:
            self._hist_restore(rtc)
        if not rtc.ref.valid and store.ref is not None:      # restoreReferenceIfNeeded
            v, age = store.ref
            if M.MIN_VALID <= v <= M.MAX_VALID:
                rtc.ref = M.RefState(v, True, age + REF_RESTORE_EXTRA_SECONDS, 0, 0)
        retry_wake = rtc.pendingSend
        info["kind"] = "retry" if retry_wake else "regular"
        self._sensor_on = clk["t"]
        if not retry_wake:
            adv(0.51)                           # initializeSensor (przy ponowieniu: dopiero przed pomiarem)

        accept_rise_now = self.manual_boot and not retry_wake
        self.manual_boot = False

        def do_measure(is_retry):
            prev = (rtc.ref.valid, rtc.ref.value, rtc.ref.rejectedCycles)
            if self.v2 and accept_rise_now and not is_retry:
                rtc.ref.deadzoneCycles = 0          # v2: fizyczny reset TX zeruje licznik strefy martwej
            mm = M.MeasurementManager(lambda: self._read(t_wake, clk, adv), adv, rtc.ref, is_retry,
                                      accept_rise_now and not is_retry)
            res = mm.run_cycle()
            if self.v2 and res.isValid:
                self._hist_accept(rtc, res, prev, is_retry)
            if rtc.ref.valid:
                store.ref = (rtc.ref.value, rtc.ref.secondsSinceRef)    # RefStore::save
            return res

        def sensor_off():
            sensor_off_at[0] = clk["t"]

        meas_ok = send_ok = esp_ok = False
        fail_reason = "UNKNOWN"
        result = M.Result()

        discovered_ok = [False]

        def init_espnow():
            ok = radio.begin()
            discovered_ok[0] = radio.discover()
            return ok

        def send_value(value):
            if not radio.known:
                return False                      # discovery przed chwila nieudane -> nie powtarzaj (ponowienie/kolejny cykl)
            payload = self._payload(rtc) if self.v2 else None
            if radio.send_with_retry(value, payload):
                return True
            for _ in range(2):
                if radio.discover():
                    if radio.send_with_retry(value, payload):
                        return True
                adv(1.0)
            return False

        if retry_wake:
            esp_ok = init_espnow()
            if esp_ok and radio.known:
                radio.shutdown()
                self._sensor_on = clk["t"]
                adv(0.51)
                fresh = do_measure(True)
                if fresh.isValid:
                    rtc.pendingValue, rtc.pendingSeries = fresh.value, fresh.acceptedSeriesCount
                sensor_off()
                esp_ok = init_espnow()
            else:
                self._sensor_on = clk["t"]          # czujnik nie byl w ogole wlaczony
                sensor_off()
            result = M.Result(value=rtc.pendingValue, isValid=True, status=M.OK, acceptedSeriesCount=rtc.pendingSeries)
            meas_ok = True
            send_ok = esp_ok and send_value(rtc.pendingValue)
        else:
            result = do_measure(False)
            meas_ok = result.isValid
            sensor_off()
            esp_ok = init_espnow()
            if not meas_ok:
                fail_reason = "JUMP_REJECTED" if result.status == M.REJECTED_JUMP else "NO_VALID_SERIES"
            else:
                rtc.pendingValue, rtc.pendingSeries = result.value, result.acceptedSeriesCount
                send_ok = esp_ok and send_value(rtc.pendingValue)

        # ----- plan snu (port 1:1) -----
        active_sec = int(clk["t"])
        sleep_s = DEEP_SLEEP_SECONDS
        if not retry_wake:
            rtc.secondsToRegular = DEEP_SLEEP_SECONDS
        else:
            rtc.secondsToRegular = rtc.secondsToRegular - active_sec if rtc.secondsToRegular > active_sec else 0

        if meas_ok and not send_ok:
            idx = rtc.pendingRetryIdx if retry_wake else 0
            allow = rtc.failedRegular < FAILED_CYCLES_NO_RETRY       # po N nieudanych cyklach brak ponowien
            if allow and idx < SEND_RETRY_COUNT and rtc.secondsToRegular > SEND_RETRY_SCHEDULE_S[idx] + SEND_RETRY_MARGIN_S:
                sleep_s = SEND_RETRY_SCHEDULE_S[idx]
                rtc.secondsToRegular -= sleep_s
                rtc.pendingSend = True
                rtc.pendingRetryIdx = idx + 1
            else:
                rtc.pendingSend = False
                rtc.pendingRetryIdx = 0
                rtc.failedRegular = min(250, rtc.failedRegular + 1)
                sleep_s = rtc.secondsToRegular if rtc.secondsToRegular > 10 else 10
        elif retry_wake:
            rtc.pendingSend = False
            rtc.pendingRetryIdx = 0
            sleep_s = rtc.secondsToRegular if rtc.secondsToRegular > 10 else 10

        if meas_ok and send_ok:
            rtc.failedRegular = 0
        # commitSession (zapis rekordu do flash)
        size = 2500 + self.rng.randint(0, 2200)
        store.commit(bytes(size))

        # wysylka logow
        if esp_ok and radio.known:
            P.flush(store, self.rx_txlog, P.Channel(self.rng, self.env.p_loss, self.env.rx_up(radio.now())), clk)

        radio.close()
        sleep_s = int(sleep_s)
        rtc.elapsedSincePrevWake = int(clk["t"]) + sleep_s
        info.update(meas=result, meas_ok=meas_ok, sendOk=send_ok, sleep=sleep_s, active=clk["t"],
                    deliveries=radio.deliveries, wifi_s=radio.wifi_s, stats=radio.stats,
                    sensor_s=(sensor_off_at[0] if sensor_off_at[0] is not None else clk["t"]) - self._sensor_on)
        self.energy["wifi_s"] += radio.wifi_s
        self.energy["sensor_s"] += (sensor_off_at[0] if sensor_off_at[0] is not None else clk["t"]) - self._sensor_on
        self.energy["active_s"] += clk["t"]
        self.energy["wakes"] += 1
        return info

    # ---- v2: historia zatwierdzonych pomiarow w TX (flash) ----
    def _hist_restore(self, rtc):
        if rtc.hist is not None:
            return
        rtc.hist = []
        h = self.store.hist2
        if h and h["pts"]:
            for v, age, syn in h["pts"]:
                rtc.hist.append([v, -(HIST_ASSUMED_GAP_S + age), syn])
            rtc.hist.sort(key=lambda p: p[1])

    def _hist_save(self, rtc):
        h = self.store.hist2
        newest = rtc.hist[-1][1] if rtc.hist else 0
        h["pts"] = [(v, newest - ts, syn) for v, ts, syn in rtc.hist]

    def _hist_accept(self, rtc, res, prev, is_retry):
        """po zaakceptowanym pomiarze: wzrost (wywoz / reset odniesienia po odrzuceniach) czysci historie"""
        pvalid, pval, prej = prev
        store = self.store
        if store.hist2 is None:                      # pierwsze uruchomienie / erase: nowa epoka, seq od 0
            epoch = 0
            while epoch == 0:
                epoch = self.rng.getrandbits(32)
            store.hist2 = dict(epoch=epoch, seq=0, pts=[])
        jump = pvalid and (res.value - pval > M.RISE_NOISE or prej >= M.MAX_REJECTED)
        if jump:
            rtc.hist = []
            rtc.cur_pt = False
        synth = res.status == M.BELOW_MIN_RANGE
        if is_retry and rtc.cur_pt and rtc.hist:
            rtc.hist[-1] = [res.value, rtc.hclock, synth]          # swiezy pomiar zastepuje oczekujacy (ten sam seq)
        else:
            rtc.hist.append([res.value, rtc.hclock, synth])
            store.hist2["seq"] += 1
        rtc.cur_pt = True
        rtc.hist = rtc.hist[-HIST_POINTS:]
        self._hist_save(rtc)

    def _payload(self, rtc):
        h = self.store.hist2
        if not h or not rtc.hist:
            return None
        pts = [(v, int(rtc.hclock - ts), syn) for v, ts, syn in reversed(rtc.hist)]      # najnowszy pierwszy
        return dict(epoch=h["epoch"], seq=h["seq"], pts=pts)

    def _read(self, t_wake, clk, adv):
        d = self.sensor.read(t_wake + clk["t"])
        adv(0.038 if d < 0 else 0.004)
        return d
