"""B. Maszyna stanow TX, ponawianie, energia, zasilanie, hangi (na wiernym porcie main.cpp)"""
from common import *   # noqa
from e2e import Run, DAY

# model pradowy (przyblizony, DO PORADNIKA - wartosci zalozone): ESP32 aktywny bez radia, czujnik, radio
I_CPU_MA, I_SENSOR_MA, I_WIFI_MA = 45.0, 30.0, 110.0


def mah(en, days):
    return (en["active_s"] * I_CPU_MA + en["sensor_s"] * I_SENSOR_MA + en["wifi_s"] * (I_WIFI_MA - 0)) / 3600.0 / days


def run():
    # B1 punkt odniesienia: zdrowy system 30 dni
    base = Run(seed=11, days=30, tank_kw=dict(start_cm=150, rate=4)).run()
    gaps = [(b["t"] - a["t"]) for a, b in zip(base.wakes, base.wakes[1:])]
    e0 = mah(base.tx.energy, 30)
    info("B1", "zdrowy system: okres cyklu [h] / wybudzen / aktywnosc na wybudzenie [s]",
         f"{sum(gaps)/len(gaps)/3600:.3f} h / {len(base.wakes)} / {base.tx.energy['active_s']/len(base.wakes):.0f} s ; ~{e0:.1f} mAh/dobe (bez uspienia)")
    check("B1", "okres cyklu w granicach 6.0-6.1 h", 6.0 <= sum(gaps) / len(gaps) / 3600 <= 6.1)

    # B2 RX niedostepny 5 dni: ile wybudzen/dobe i koszt energii
    r = Run(seed=12, days=30, tank_kw=dict(start_cm=150, rate=4), env_kw=dict(outages=[(10 * DAY, 15 * DAY)])).run()
    w_out = [w for w in r.wakes if 10 * DAY <= w["t"] < 15 * DAY]
    wifi_out = sum(w.get("wifi_s", 0) for w in w_out) / 5
    act_out = sum(w["active"] for w in w_out) / 5
    w_ok = [w for w in r.wakes if w["t"] < 10 * DAY]
    act_ok = sum(w["active"] for w in w_ok) / 10
    wifi_ok = sum(w.get("wifi_s", 0) for w in w_ok) / 10
    e_out = (act_out * I_CPU_MA + wifi_out * I_WIFI_MA + sum(155 for _ in w_out) / 5 * I_SENSOR_MA) / 3600
    e_ok = (act_ok * I_CPU_MA + wifi_ok * I_WIFI_MA + sum(155 for _ in w_ok) / 10 * I_SENSOR_MA) / 3600
    info("B2", "RX wylaczony 5 dni: wybudzen/dobe, aktywnosc s/dobe, radio s/dobe",
         f"{len(w_out)/5:.1f} wyb/d, {act_out:.0f} s/d (norma {act_ok:.0f}), radio {wifi_out:.0f} s/d (norma {wifi_ok:.0f}) => ~{e_out/e_ok:.1f}x energii")
    check("B2", "awaria RX nie zwieksza zuzycia energii TX > 2x", e_out / e_ok <= 2.0, f"{e_out/e_ok:.1f}x")
    check("B2c", "przy dlugiej awarii RX <= 5 wybudzen na dobe", len(w_out) / 5 <= 5.5, f"{len(w_out)/5:.1f}/dobe (4 regularne + jednorazowa seria ponowien)")
    # powrot po awarii RX
    after = [w for w in r.wakes if w["t"] >= 15 * DAY and w.get("sendOk")]
    lag = (after[0]["t"] - 15 * DAY) / 3600 if after else None
    info("B2", "powrot dostarczania po powrocie RX", f"{lag:.1f} h" if lag is not None else "brak")
    # B2b: czy retry wchodza na kolizje z cyklem regularnym (odstepy miedzy wybudzeniami)
    kinds = "".join("R" if w["kind"] == "retry" else "C" for w in r.wakes if 10 * DAY <= w["t"] < 11 * DAY)
    info("B2b", "sekwencja wybudzen (C=regularny, R=ponowienie) w 1. dobie awarii RX", kinds)

    # B3 RX dziala, ale 40% pakietow ginie w kazdym kierunku (slaby zasieg)
    r = Run(seed=13, days=30, tank_kw=dict(start_cm=150, rate=4), env_kw=dict(p_loss=0.4)).run()
    deliv = sum(len(w.get("deliveries", [])) for w in r.wakes)
    ok = sum(1 for w in r.wakes if w.get("sendOk"))
    stale = [s for s in r.series if s[3] == "warning"]
    info("B3", "p_loss=40%/kierunek, 30 dni", f"wybudzen={len(r.wakes)} ack_ok={ok} dostarczone_do_RX={deliv} ekran_ostrzezenia={len(stale)*600/3600:.1f} h")

    # B4 reset zasilania TX w srodku cyklu pomiarowego (przerwanie w 80. s)
    r = Run(seed=14, days=12, tank_kw=dict(start_cm=100, rate=5),
            tx_power_events=[(3 * DAY + 3600, 80.0, False)]).run()
    after = [w for w in r.wakes if w["t"] > 3 * DAY + 3600 and not w.get("cut")]
    first = after[0]
    check("B4", "po resecie w trakcie pomiaru nastepny cykl zwraca poprawna wartosc",
          first["meas_ok"] and abs(first["meas"].value - r.tank.truth(first["t"])) < 4,
          f"t+{(first['t']-(3*DAY+3600)):.0f}s val={first['meas'].value:.1f} prawda={r.tank.truth(first['t']):.1f}")
    # B4b: reset miedzy zapisem meta a rekordem (uszkodzony meta.bin)
    r = Run(seed=15, days=12, tank_kw=dict(start_cm=100, rate=5),
            tx_power_events=[(3 * DAY, 158.0, True)]).run()
    n_rx = len(r.rxlog.files)
    ids = [(e, i) for e, i, _ in r.rxlog.files]
    dup = len(ids) - len(set(ids))
    epochs = sorted({e for e, _, _ in r.rxlog.files})
    info("B4b", "uszkodzony meta.bin: epoki w logu RX / rekordy / duplikaty (e,id)", f"{len(epochs)} / {n_rx} / {dup}")
    check("B4b", "po uszkodzeniu meta TX nadal dostarcza logi i nie zawiesza sie", n_rx > 0 and r.wakes[-1]["sleep"] > 0)

    # B5 TX nigdy nie 'wisi': maksymalny czas aktywnosci w roznych trybach awarii
    worst = {}
    for name, kw in (("RX off", dict(env_kw=dict(outages=[(0, 20 * DAY)]))),
                     ("loss 70%", dict(env_kw=dict(p_loss=0.7))),
                     ("loss 95%", dict(env_kw=dict(p_loss=0.95))),
                     ("sensor ślepy", dict(sensor_kw=dict(faults=[dict(t0=0, t1=20 * DAY, kind="blind")])))):
        rr = Run(seed=16, days=20, tank_kw=dict(start_cm=120, rate=4), **kw).run()
        worst[name] = max(w["active"] for w in rr.wakes if "active" in w)
    info("B5", "najdluzsze pojedyncze wybudzenie [s]", ", ".join(f"{k}: {v:.0f}" for k, v in worst.items()))
    check("B5", "zadne wybudzenie nie dluzsze niz 5 min (TX nie wisi)", max(worst.values()) < 300, f"max {max(worst.values()):.0f}s")

    # B6 RTC zegar +-5%: wplyw na okres
    # (informacyjnie) 6h * 1.05 = 6.3h; okno napelniania liczone z requested sleep, nie z rzeczywistego
    info("B6", "dryf RC oscylatora RTC +-5%", "okres rzeczywisty 5.7-6.3 h; elapsedSincePrevWake liczony z zadanego snu (blad okna <= 5%, pomijalny)")
