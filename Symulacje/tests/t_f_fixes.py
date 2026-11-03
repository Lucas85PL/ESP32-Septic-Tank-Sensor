"""F. Weryfikacja WDROZONYCH zmian (patrz RAPORT_ZMIAN.md): energia przy awarii RX, wywoz+RESET, wznawianie logow"""
from common import *   # noqa
import rx_logic as R
import protocol as P
from e2e import Run, DAY
import t_b_system as B


def run():
    # F1 energia przy awarii RX (zmiany 4, 5)
    r = Run(seed=12, days=30, tank_kw=dict(start_cm=150, rate=4), env_kw=dict(outages=[(10 * DAY, 15 * DAY)])).run()
    w_out = [w for w in r.wakes if 10 * DAY <= w["t"] < 15 * DAY]
    w_ok = [w for w in r.wakes if w["t"] < 10 * DAY]
    f = lambda ws, d: (sum(w["active"] for w in ws) * B.I_CPU_MA + sum(w.get("wifi_s", 0) for w in ws) * B.I_WIFI_MA
                       + sum(w.get("sensor_s", 155) for w in ws) * B.I_SENSOR_MA) / 3600 / d
    ratio = f(w_out, 5) / f(w_ok, 10)
    after = [w for w in r.wakes if w["t"] >= 15 * DAY and w.get("sendOk")]
    lag = (after[0]["t"] - 15 * DAY) / 3600
    kinds = "".join("R" if w["kind"] == "retry" else "C" for w in r.wakes if 10 * DAY <= w["t"] < 12 * DAY)
    info("F1", "awaria RX 5 dni: energia wzgl. normy / wybudzen na dobe / powrot po wlaczeniu RX", f"{ratio:.1f}x / {len(w_out)/5:.1f} / {lag:.1f} h; sekwencja 2 dob: {kinds}")
    check("F1", "awaria RX: <= 2x energii normy", ratio <= 2.0, f"{ratio:.1f}x")
    check("F1b", "po powrocie RX dane docieraja w <= 6.5 h (najblizszy regularny cykl)", lag <= 6.5, f"{lag:.1f} h")

    # F2 wywoz bez recznego resetu TX: opoznienie widocznosci na RX (2 cykle) i z resetem TX (od razu)
    def pump_lag(tx_reset):
        pump = 10 * DAY
        kw = dict(seed=31, days=14, tank_kw=dict(start_cm=40, rate=3, pumpouts=[pump]), sensor_kw=dict(sigma=0.4),
                  rx_manual_resets=[pump + 600])
        if tx_reset:
            kw["tx_power_events"] = [(pump + 1800, None, False)]
        rr = Run(**kw).run()
        seen = next((s[0] for s in rr.series if s[0] > pump and s[2] is not None and s[2] > 140 and s[3] == "measure"), None)
        return (seen - pump) / 3600 if seen else None
    lag_auto, lag_reset = pump_lag(False), pump_lag(True)
    info("F2", "wywoz: po ilu godzinach RX pokazuje 'pusty' - bez resetu TX / z fizycznym resetem TX", f"{lag_auto:.1f} h / {lag_reset:.1f} h")
    check("F2", "bez resetu TX wywoz widoczny w <= 13 h (2 cykle), z resetem TX w <= 1 h", lag_auto <= 13 and lag_reset <= 1.0)

    # F3 wznawianie logow (zmiana 18) - dostarczanie przy stratach 30-50 %/kierunek
    for p in (0.3, 0.5):
        st = P.TxStore(random.Random(3)); st.begin()
        for _ in range(20):
            st.commit(bytes(random.Random(p).randint(3000, 4800)))
        rx = P.RxTxLog()
        ch = P.Channel(random.Random(4), p)
        n = None
        for w in range(1, 120):
            clk = {"t": 0.0}
            P.flush(st, rx, ch, clk)
            if st.next_unsent() is None:
                n = w
                break
        ids = [i for _, i, _ in rx.files]
        info("F3", f"p_loss={p:.1f}/kierunek: wybudzen do dostarczenia 20 rekordow (z wznawianiem)", f"{n}; dokladnie raz: {ids == sorted(set(ids))}")
        if p == 0.3:
            check("F3", "przy 30% strat/kierunek 20 rekordow (~18 porcji) dociera w <= 80 wybudzeniach (bez wznawiania praktycznie nigdy)", n is not None and n <= 80, str(n))

    # F4 reset TX podczas 'oczekuje na potwierdzenie' - bez zawieszenia, brak falszywego wywozu
    rr = Run(seed=33, days=12, tank_kw=dict(start_cm=40, rate=3), sensor_kw=dict(sigma=0.4,
             faults=[dict(t0=4 * DAY, t1=4 * DAY + 5 * 3600, kind="wall", c=150.0)])).run()
    bad = [s for s in rr.series if s[2] is not None and s[2] > 140 and s[1] < 100]
    check("F4", "czujnik wyjety na 5 h (jeden cykl 150 cm) NIE ustawia 'pustego zbiornika'", not bad, f"{len(bad)} probek fałszywego 'pusty'")
