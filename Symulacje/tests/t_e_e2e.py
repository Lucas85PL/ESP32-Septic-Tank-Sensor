"""E. End-to-end Monte Carlo: zbiornik -> czujnik z usterkami -> TX -> radio -> RX (porty firmware)"""
from common import *   # noqa
from e2e import Run, DAY
import statistics


def fault_set(rng, days):
    f = []
    for _ in range(2):
        t0 = rng.uniform(2, days - 3) * DAY
        f.append(dict(t0=t0, t1=t0 + rng.uniform(12, 48) * 3600, kind="blind"))
    for _ in range(2):
        t0 = rng.uniform(2, days - 3) * DAY
        f.append(dict(t0=t0, t1=t0 + rng.uniform(12, 36) * 3600, kind="echo", c=25.4, p=0.6))
    t0 = rng.uniform(2, days - 3) * DAY
    f.append(dict(t0=t0, t1=t0 + rng.uniform(12, 30) * 3600, kind="random", p=0.4))
    return f


def metrics(run, ignore_first_days=1.0):
    ser = [s for s in run.series if s[0] > ignore_first_days * DAY]
    good = stale = wrong = 0
    errs = []
    false_full = 0
    for t, truth, shown, screen, led in ser:
        if shown is None:
            continue
        e = abs(shown - max(truth, 25.0))   # ponizej 25 cm czujnik raportuje 25.0
        errs.append(e)
        if screen == "warning":
            stale += 1
        elif e <= 10:
            good += 1
        else:
            wrong += 1
        if shown <= 35 and truth >= 55 and run.tank.truth(t - 7 * 3600) >= 55:   # 7 h tolerancji na opoznienie cyklu po wywozie
            false_full += 1
    n = max(1, good + stale + wrong)
    return dict(good=good / n * 100, stale=stale / n * 100, wrong=wrong / n * 100,
                mean_err=statistics.mean(errs) if errs else float("nan"),
                false_full_h=false_full * 600 / 3600)


def run(n=24, days=60):
    # E1 baseline: realistyczne usterki z logu uzytkownika
    agg = []
    for seed in range(n):
        rng = random.Random(1000 + seed)
        pump = [rng.uniform(18, 30) * DAY]
        kw = dict(seed=seed, days=days,
                  tank_kw=dict(start_cm=rng.uniform(80, 130), rate=rng.uniform(3, 8), pumpouts=pump),
                  sensor_kw=dict(faults=fault_set(rng, days), sigma=rng.uniform(0.3, 1.5)),
                  rx_manual_resets=[pump[0] + 3600])
        agg.append(metrics(Run(**kw).run()))
    avg = {k: statistics.mean(a[k] for a in agg) for k in agg[0]}
    info("E1", f"baseline {n} przebiegow x {days} dni (bledy z logu: slepota, echo 25.4, losowe)",
         f"widok DOBRY {avg['good']:.1f}% | ALARM/nieaktualny {avg['stale']:.1f}% | BLEDNY {avg['wrong']:.1f}% | sredni blad {avg['mean_err']:.1f} cm | falszywe 'pelny' {avg['false_full_h']:.1f} h/przebieg")
    check("E1", "widok DOBRY >= 85% czasu w warunkach z usterkami", avg["good"] >= 85, f"{avg['good']:.1f}%")
    check("E1b", "falszywy komunikat 'prawie pelny' (<=35 cm przy prawdzie >=55) < 2 h/przebieg", avg["false_full_h"] < 2.0, f"{avg['false_full_h']:.1f} h")

    # E2 zdrowy system - bez usterek
    agg0 = [metrics(Run(seed=s, days=days, tank_kw=dict(start_cm=120, rate=5, pumpouts=[25 * DAY]),
                        sensor_kw=dict(sigma=0.5)).run()) for s in range(10)]
    a0 = {k: statistics.mean(a[k] for a in agg0) for k in agg0[0]}
    info("E2", "bez usterek, 10 przebiegow", f"DOBRY {a0['good']:.1f}% | alarm {a0['stale']:.1f}% | BLEDNY {a0['wrong']:.1f}% | blad {a0['mean_err']:.2f} cm")
    check("E2", "zdrowy czujnik: widok DOBRY >= 97%", a0["good"] >= 97, f"{a0['good']:.1f}%")

    # E3 wplyw temperatury (czujnik zaklada 20 C): zima 0 C / lato 30 C
    for tc in (-10, 0, 30):
        r = Run(seed=5, days=10, tank_kw=dict(start_cm=100, rate=3), sensor_kw=dict(temp_c=tc, sigma=0.3)).run()
        errs = [s[2] - s[1] for s in r.series if s[2] is not None and s[0] > DAY]
        info("E3", f"temperatura powietrza {tc} C (stala predkosc dzwieku 20 C)", f"srednie przesuniecie wskazania {statistics.mean(errs):+.1f} cm przy ~100 cm")

    # E4 zimny start TX po wymianie baterii w trakcie napelniania + RX wylaczony w tym czasie
    r = Run(seed=8, days=20, tank_kw=dict(start_cm=110, rate=6),
            tx_power_events=[(8 * DAY, None, False)],
            env_kw=dict(outages=[(7.5 * DAY, 9.5 * DAY)])).run()
    m = metrics(r)
    info("E4", "wymiana baterii TX (zimny start) podczas awarii RX", f"DOBRY {m['good']:.1f}% | alarm {m['stale']:.1f}% | BLEDNY {m['wrong']:.1f}%")

    # E5 pelny zbiornik: wejscie w strefe martwa na kilka dni + wywoz
    r = Run(seed=9, days=25, tank_kw=dict(start_cm=60, rate=7, pumpouts=[14 * DAY]),
            sensor_kw=dict(dz_mode="scatter", sigma=0.4), rx_manual_resets=[14 * DAY + 3600]).run()
    m = metrics(r)
    info("E5", "zbiornik dochodzi do 100% i jest oprozniany", f"DOBRY {m['good']:.1f}% | alarm {m['stale']:.1f}% | BLEDNY {m['wrong']:.1f}%")

    # E6 sprzet: stala sciana 30-150 (czujnik wyjety) 24-48 h, potem powrot
    r = Run(seed=10, days=20, tank_kw=dict(start_cm=110, rate=5),
            sensor_kw=dict(faults=[dict(t0=8 * DAY, t1=9.5 * DAY, kind="wall", c=90.0)])).run()
    m = metrics(r)
    info("E6", "czujnik wyjety na 36 h (stala 'sciana' 90 cm)", f"DOBRY {m['good']:.1f}% | alarm {m['stale']:.1f}% | BLEDNY {m['wrong']:.1f}%")
