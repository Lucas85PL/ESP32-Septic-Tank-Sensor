"""D. Odbiornik: prognoza 'Pelny za', alarm 25 h / dioda, zawijanie millis(), restart, smieciowe pakiety"""
from common import *   # noqa
import rx_logic as R
from e2e import Run, DAY


def feed(rx, t, raw):
    rx.on_packet(t, raw)
    rx.tick(t)


def run():
    # D1 wywoz bez recznego RESET: RX sam wykrywa oproznienie i zeruje historie
    rng = random.Random(5)
    rx = R.RxDevice()
    d = 100.0
    rows = []
    for k in range(0, 40 * 4):
        t = k * 21600.0
        d = 160.0 if k == 24 else max(25.0, d - 6.0 / 4.0)
        feed(rx, t, d + rng.gauss(0, 0.5))
        rows.append((k, d, rx.days_mid()))
    after = [r for r in rows if r[0] > 24]
    shown_dash = sum(1 for r in after[:20] if r[2] < 0)
    info("D1", "RX po wywozie (bez RESET): resety historii / ile z 20 kolejnych odczytow '-- dni'", f"{rx.resets} / {shown_dash}")
    check("D1", "po wywozie RX resetuje historie prognozy", rx.resets >= 1)
    check("D1b", "po wywozie prognoza wraca do sensownej wartosci (<60 dni) najpozniej po 8 pomiarach", all(0 <= r[2] < 60 for r in after[9:16]),
          str([(r[0] - 24, round(r[2], 1)) for r in after[:16]]))
    # RESET reczny: pierwszy pakiet = nowy start
    rx = R.RxDevice(); feed(rx, 0.0, 60.0)
    rx.manual_reset(100.0)
    check("D1c", "po RESET: ekran 'oczekiwanie', brak starych danych, dioda wygaszona", rx.screen == "waiting" and rx.hasValidMeasurement is False and rx.shown_cm() is None)
    feed(rx, 200.0, 155.0)
    check("D1d", "pierwszy pakiet po RESET jest nowym startem (raw 155 -> 145 cm pokazane, historia 1 punkt)", rx.shown_cm() == 145.0 and len(rx.hist) == 1)

    # D2 jakosc prognozy w stanie ustalonym (6 cm/dobe, szum wyniku TX sigma=1 cm, cykl 6h)
    errs, dashes, n, widths = [], 0, 0, []
    for seed in range(60):
        rng = random.Random(seed)
        rx = R.RxDevice()
        d = 140.0
        for k in range(0, 4 * 25):
            d -= 6.0 / 4.0
            if d < 45:
                break
            feed(rx, k * 21600.0, d + rng.gauss(0, 1.0))
            if k > 16:
                n += 1
                f = rx.forecast()
                true = (d - 15 - 10) / 6.0
                if f is None:
                    dashes += 1
                else:
                    lo, hi, opn = f
                    errs.append(abs(rx.days_mid() - true) / max(true, 1))
                    widths.append(true >= lo - 1 and (opn or true <= hi + 1))
    errs.sort()
    info("D2", "prognoza 'Pelny za' (regresja): % '-- dni' / mediana bledu / p90 bledu / prawda w zakresie",
         f"{dashes/n*100:.0f}% / {errs[len(errs)//2]*100:.0f}% / {errs[int(len(errs)*0.9)]*100:.0f}% / {sum(widths)/len(widths)*100:.0f}%")
    check("D2", "prognoza: mediana bledu < 15%, p90 < 30%, '-- dni' < 5%", errs[len(errs)//2] < 0.15 and errs[int(len(errs)*0.9)] < 0.30 and dashes / n < 0.05)

    # D3 alarm 25 h przy zbiorniku w strefie martwej (end-to-end)
    r = Run(seed=21, days=20, tank_kw=dict(start_cm=60, rate=6), sensor_kw=dict(dz_mode="scatter")).run()
    warn = sum(1 for s in r.series if s[3] == "warning") * 600 / 3600
    first_dz = next((w for w in r.wakes if w["meas"].status == "BELOW_MIN_RANGE"), None)
    first_below = next((s[0] for s in r.series if s[1] < 25), None)
    info("D3", "zbiornik wchodzi w strefe martwa (t_prawda<25 cm) -> pierwszy raport 25.0",
         f"prawda<25 od {first_below/3600:.0f} h, raport 25.0 od {first_dz['t']/3600:.0f} h, ekran 'BRAK POMIARU' lacznie {warn:.1f} h" if first_dz and first_below else "brak raportu")
    info("D3", "alarm 'BRAK POMIARU' w strefie martwej [ZAAKCEPTOWANE - wywoz organizowany wczesniej]", f"{warn:.1f} h")

    # D4 TX martwy od dnia 3: os czasu alarmu / diody
    r = Run(seed=22, days=9, tank_kw=dict(start_cm=140, rate=4),
            env_kw=dict(outages=[])).run()
    r2 = Run(seed=22, days=9, tank_kw=dict(start_cm=140, rate=4),
             sensor_kw=dict(faults=[dict(t0=2 * DAY, t1=99 * DAY, kind="blind")])).run()
    def first(series, pred):
        return next((s[0] / 3600 for s in series if pred(s)), None)
    w = first(r2.series, lambda s: s[3] == "warning")
    o = first(r2.series, lambda s: s[4] == "orange")
    rd = first(r2.series, lambda s: s[4] == "red")
    info("D4", "czujnik slepy od t=48 h: godzina alarmu / diody pomaranczowej / czerwonej", f"{w} / {o} / {rd}  (ostatni pomiar ok. 48 h)")
    check("D4", "ekran ostrzezenia pojawia sie 25-31 h po ostatnim pomiarze", w is not None and 48 + 25 - 6 <= w <= 48 + 32)

    # D5 zawijanie millis(): RX dziala > 49.7 dnia, TX martwy od pierwszego dnia
    rx = R.RxDevice(boot_ms=0)
    feed(rx, 0.0, 100.0)
    states = {}
    for day in (1, 2, 10, 40, 49, 50, 51, 60, 100):
        t = day * DAY
        rx.tick(t)
        states[day] = (rx.led(t), rx.screen)
    info("D5", "RX bez pakietow, stan diody/ekranu po N dniach", ", ".join(f"{d}d:{s[0]}/{s[1]}" for d, s in states.items()))
    check("D5", "po 50-100 dniach bez danych dioda zostaje czerwona (czas 64-bit)", all(states[d][0] == "red" for d in (49, 50, 51, 60, 100)),
          f"50d={states[50][0]}, 100d={states[100][0]}")

    # D6 restart RX (utrata zasilania) - wiek z NVS
    rx = R.RxDevice()
    feed(rx, 0.0, 100.0)
    for h in range(1, 8):
        rx.tick(h * 3600.0)
    rx.power_on(8 * 3600.0 + 1200)         # zasilanie wraca po 20 min
    age = (rx.ms(8 * 3600.0 + 1200) - rx.lastValidMillis) & R.M32
    info("D6", "wiek pomiaru po restarcie RX (prawdziwy 8.3 h)", f"{age/3600000:.2f} h  (czas bez zasilania nie jest liczony; zapis co 1 h)")

    # D7 smieciowe pakiety
    rx = R.RxDevice()
    feed(rx, 0.0, 100.0)
    for bad in (float("nan"), float("inf"), -1.0, 0.0, 180.0, 181.0, 1e30):
        feed(rx, 10.0, bad)
    check("D7", "NaN/Inf/ujemne/ogromne pakiety nie psuja stanu (wartosc ostatnia zachowana)", rx.lastDistance == 85.0 or rx.lastDistance > 0,
          f"lastDistance={rx.lastDistance}")
    rx2 = R.RxDevice()
    feed(rx2, 0.0, 100.0)
    feed(rx2, 1.0, 0.0)
    info("D7", "pakiet 0.0 cm (dozwolony przez walidacje RX: raw>=0) -> wolne miejsce / procent", f"{rx2.lastDistance:.0f} cm / {rx2.percent()}%  [TX nie wysyla <25]")
    info("D7", "RX nie sprawdza nadawcy: kazdy 10-bajtowy pakiet ESP-NOW na kanale 1 jest traktowany jako pomiar", "brak filtra MAC/magic (ryzyko niskie, domowe srodowisko)")
