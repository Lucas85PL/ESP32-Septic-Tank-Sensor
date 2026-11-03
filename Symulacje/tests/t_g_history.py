"""G. Propozycja v2: historia pomiarow w TX (flash) wysylana w pakiecie, RX bez wlasnej historii.
 Porownanie STARY (RX zbiera historie sam, 8 pkt) vs NOWY (v2: 14 pkt w pakiecie, prior 6 cm/dobe do 36 h, odciecie po RESET)."""
from common import *   # noqa
from e2e import Run, DAY
import rx_v2 as R2
import rx_logic as R
import statistics


# ---------- narzedzia ----------
def fc_stats(run, t0, t1, rate, min_truth=40.0):
    """dostepnosc prognozy (gdy RX dziala) i blad wzgledny dni do 'pelnego' wzgledem prawdy"""
    up = avail = 0
    errs, errs_o, errs_g = [], [], []
    n_o = n_g = 0
    for (t, truth, st), ser in zip(run.fc, run.series):
        if not (t0 <= t < t1) or ser[3] == "off":
            continue
        up += 1
        if st is None:
            continue
        avail += 1
        days, col = st
        if truth <= min_truth:
            continue
        true = (truth - 25.0) / rate
        e = abs(days - true) / max(true, 1.0)
        errs.append(e)
        (errs_o if col == "orange" else errs_g).append(e)
    def q(v, p):
        v = sorted(v)
        return v[int(len(v) * p)] if v else float("nan")
    return dict(avail=avail / up * 100 if up else float("nan"), n=up, med=q(errs, 0.5), p90=q(errs, 0.9),
                med_o=q(errs_o, 0.5), med_g=q(errs_g, 0.5), frac_o=len(errs_o) / max(1, len(errs)) * 100)


def first_fc(run, t_after, color=None):
    for (t, truth, st) in run.fc:
        if t >= t_after and st is not None and (color is None or st[1] == color):
            return (t - t_after) / 3600.0
    return None


def pct(x):
    return f"{x * 100:.0f}%"


def agg(vals):
    v = [x for x in vals if x is not None]
    return (statistics.median(v), max(v), len(v)) if v else (None, None, 0)


# ---------- G1: po wywozie - szybkosc i dokladnosc ----------
def g1(n=12):
    out = {}
    for label, v2 in (("STARY", False), ("NOWY", True)):
        first_any, first_green, st_post, st_pre = [], [], [], []
        for seed in range(n):
            rate = 6.0 if seed % 2 == 0 else [3.0, 4.5, 7.0, 8.0, 5.0, 3.5][seed // 2 % 6]
            tp = 8 * DAY
            r = Run(seed=seed, days=16, v2=v2,
                    tank_kw=dict(start_cm=100, rate=rate, rate_var=0.2, pumpouts=[tp]),
                    sensor_kw=dict(sigma=0.6),
                    rx_manual_resets=[tp + 3600], tx_power_events=[(tp + 7200, None, False)]).run()
            first_any.append(first_fc(r, tp + 7200))
            first_green.append(first_fc(r, tp + 7200, "green"))
            st_post.append(fc_stats(r, tp + 7200, tp + 7200 + 6 * DAY, rate))
            st_pre.append(fc_stats(r, 4 * DAY, tp - 3600, rate))
        out[label] = dict(first_any=agg(first_any), first_green=agg(first_green),
                          post=dict(avail=statistics.mean(s["avail"] for s in st_post),
                                    med=statistics.median(s["med"] for s in st_post), p90=statistics.median(s["p90"] for s in st_post),
                                    med_o=statistics.median([s["med_o"] for s in st_post if s["med_o"] == s["med_o"]] or [float("nan")]),
                                    med_g=statistics.median([s["med_g"] for s in st_post if s["med_g"] == s["med_g"]] or [float("nan")]),
                                    frac_o=statistics.mean(s["frac_o"] for s in st_post)),
                          pre=dict(avail=statistics.mean(s["avail"] for s in st_pre), med=statistics.median(s["med"] for s in st_pre),
                                   p90=statistics.median(s["p90"] for s in st_pre)))
    o, nw = out["STARY"], out["NOWY"]
    info("G1", f"po wywozie (RX RESET +1 h, TX reset +2 h), {n} przebiegow: godz. do 1. prognozy [mediana/max] STARY | NOWY",
         f"STARY {o['first_any'][0]:.0f}/{o['first_any'][1]:.0f} h | NOWY {nw['first_any'][0]:.0f}/{nw['first_any'][1]:.0f} h")
    info("G1", "godz. do prognozy 'zielonej' (z regresji) STARY | NOWY",
         f"STARY {o['first_green'][0]:.0f}/{o['first_green'][1]:.0f} h | NOWY {nw['first_green'][0]:.0f}/{nw['first_green'][1]:.0f} h")
    info("G1", "blad prognozy w 6 dniach po wywozie [mediana bledu | p90 | dostepnosc] STARY | NOWY",
         f"STARY {pct(o['post']['med'])} | {pct(o['post']['p90'])} | {o['post']['avail']:.0f}%  ||  "
         f"NOWY {pct(nw['post']['med'])} | {pct(nw['post']['p90'])} | {nw['post']['avail']:.0f}%  "
         f"(orange: {pct(nw['post']['med_o'])}, green: {pct(nw['post']['med_g'])}, udzial pomaranczowej {nw['post']['frac_o']:.0f}%)")
    info("G1", "stan ustalony przed wywozem (dni 4-8) [mediana bledu | p90 | dostepnosc] STARY | NOWY",
         f"STARY {pct(o['pre']['med'])} | {pct(o['pre']['p90'])} | {o['pre']['avail']:.0f}%  ||  NOWY {pct(nw['pre']['med'])} | {pct(nw['pre']['p90'])} | {nw['pre']['avail']:.0f}%")
    check("G1", "NOWY: pierwsza prognoza (pomaranczowa) od razu po wywozie (<= 6 h od resetu TX)", nw["first_any"][1] <= 6, f"max {nw['first_any'][1]:.1f} h")
    check("G1", "NOWY: prognoza zielona (regresja) po <= 42 h od resetu TX", nw["first_green"][1] <= 42, f"max {nw['first_green'][1]:.0f} h")
    check("G1", "NOWY: stan ustalony nie gorszy od STAREGO (mediana bledu nie wieksza o > 3 pp)",
          nw["pre"]["med"] <= o["pre"]["med"] + 0.03, f"{pct(nw['pre']['med'])} vs {pct(o['pre']['med'])}")


def g1b(n=5):
    """czuleosc prioru 6 cm/dobe na rzeczywiste tempo napelniania (tylko NOWY)"""
    rows = []
    for rate in (3.0, 4.0, 5.0, 6.0, 7.0, 8.0):
        eo, eg = [], []
        for seed in range(n):
            tp = 8 * DAY
            r = Run(seed=seed, days=14, v2=True, tank_kw=dict(start_cm=100, rate=rate, rate_var=0.2, pumpouts=[tp]), sensor_kw=dict(sigma=0.6),
                    rx_manual_resets=[tp + 3600], tx_power_events=[(tp + 7200, None, False)]).run()
            for (t, truth, st), ser in zip(r.fc, r.series):
                if st is None or not (tp + 7200 <= t < tp + 7200 + 6 * DAY) or truth <= 40:
                    continue
                true = (truth - 25.0) / rate
                e = (st[0] - true) / max(true, 1.0)
                (eo if st[1] == "orange" else eg).append(e)
        med = lambda v: statistics.median(v) if v else float("nan")
        rows.append((rate, med(eo), max([abs(x) for x in eo] or [0]), med(eg)))
    info("G1b", "prior 6 cm/dobe: blad faz POMARANCZOWEJ [mediana ze znakiem (+ = za pozno) | max] i ZIELONEJ, wg prawdziwego tempa",
         " ; ".join(f"{r:.0f} cm/d: {pct(a)} | {pct(b)} / zielona {pct(c)}" for r, a, b, c in rows))
    ok = all(abs(a) <= 0.55 for r, a, b, c in rows if 3 <= r <= 8)
    check("G1b", "faza pomaranczowa: mediana bledu <= 55% dla tempa 3-8 cm/dobe (prior orientacyjny)", ok, "")
    check("G1b", "faza zielona: mediana bledu <= 15% niezaleznie od tempa", all(abs(c) <= 0.15 for r, a, b, c in rows))


def g3b():
    """margines strefy martwej: czujnik poza zbiornikiem 30 h vs 42 h - czy TX wysle sztuczne 25.0"""
    res = {}
    for hours in (30, 36, 42):
        sent = 0
        for seed in range(12):
            t0 = 8 * DAY + seed * 1800.0
            r = Run(seed=seed, days=14, v2=True, tank_kw=dict(start_cm=83, rate=6, rate_var=0.2),
                    sensor_kw=dict(sigma=0.6, faults=[dict(t0=t0, t1=t0 + hours * 3600, kind="below", p=0.8)])).run()
            sent += 1 if any(getattr(w.get("meas"), "status", "") == "BELOW_MIN_RANGE" and t0 <= w["t"] < t0 + hours * 3600 for w in r.wakes) else 0
        res[hours] = sent
    info("G3b", "czujnik poza zbiornikiem (odczyty < 25 cm), prawdziwy poziom ~35 cm: w ilu z 12 przebiegow TX wyslal sztuczne 25.0 (=100%)",
         " ; ".join(f"{h} h: {c}/12" for h, c in res.items()))
    check("G3b", "30 h poza zbiornikiem: TX NIE wysyla sztucznego 25.0", res[30] == 0, f"{res[30]}/12")


# ---------- G2: krotkie zaniki zasilania RX ----------
def g2(n=12):
    res = {}
    for label, v2 in (("STARY", False), ("NOWY", True)):
        av, med = [], []
        for seed in range(n):
            rng = random.Random(seed)
            cuts = []
            for _ in range(3):
                a = rng.uniform(5, 10) * DAY
                cuts.append((a, a + rng.uniform(300, 3600)))
            cuts = sorted(cuts)
            r = Run(seed=seed, days=12, v2=v2, tank_kw=dict(start_cm=140, rate=5, rate_var=0.2),
                    sensor_kw=dict(sigma=0.6), rx_power_cycles=cuts).run()
            s = fc_stats(r, 5 * DAY, 11 * DAY, 5.0)
            av.append(s["avail"])
            med.append(s["med"])
        res[label] = (statistics.mean(av), min(av), statistics.median(med))
    info("G2", f"3 krotkie zaniki RX (5-60 min) w dniach 5-10, {n} przebiegow: dostepnosc prognozy [srednia/min] | mediana bledu STARY | NOWY",
         f"STARY {res['STARY'][0]:.0f}%/{res['STARY'][1]:.0f}% blad {pct(res['STARY'][2])} | NOWY {res['NOWY'][0]:.0f}%/{res['NOWY'][1]:.0f}% blad {pct(res['NOWY'][2])}")
    check("G2", "NOWY: po krotkich zanikach RX prognoza dostepna >= 97% czasu (STARY traci ok. 42 h po kazdym)", res["NOWY"][1] >= 97, f"min {res['NOWY'][1]:.0f}%")
    check("G2", "NOWY: blad po zanikach nie gorszy niz bez nich (mediana <= 15%)", res["NOWY"][2] <= 0.15, pct(res["NOWY"][2]))


# ---------- G3: Twoj workflow wywozu ----------
def g3():
    """TX wyjety 30 h (odczyty < 25 cm), wywoz do pustego, TX z powrotem, RX RESET, zaraz TX reset"""
    rows = []
    for name, order, hours in (("RX->TX (Twoj workflow), 30 h", "rx_tx", 30), ("RX->TX, 24 h", "rx_tx", 24), ("TX->RX (odwrotnie), 30 h", "tx_rx", 30),
                               ("bez RESET RX, 30 h", "no_rx", 30)):
        for v2 in (False, True):
            worst_stale, deadzone_sent, firsts, shown_after = [], 0, [], []
            for seed in range(8):
                t0 = 8 * DAY + seed * 3600.0
                t_back = t0 + hours * 3600
                t_rx = t_back + 1800
                t_tx = t_back + (2400 if order == "rx_tx" else 0)
                if order == "tx_rx":
                    t_tx, t_rx = t_back + 600, t_back + 1200
                kw = dict(seed=seed, days=14, v2=v2,
                          tank_kw=dict(start_cm=83, rate=6, rate_var=0.2, pumpouts=[t0 + 18 * 3600]),
                          sensor_kw=dict(sigma=0.6, faults=[dict(t0=t0, t1=t_back, kind="below", p=0.8)]),
                          tx_power_events=[(t_tx, None, False)])
                if order != "no_rx":
                    kw["rx_manual_resets"] = [t_rx]
                r = Run(**kw).run()
                deadzone_sent += sum(1 for w in r.wakes if w.get("meas") is not None and getattr(w["meas"], "status", "") == "BELOW_MIN_RANGE" and w["t"] < t_tx)
                # stare dane: prognoza < 12 dni w oknie 3-72 h po resecie TX (prawda ok. 20 dni)
                stale = [st[0] for (t, truth, st) in r.fc if t_tx + 3 * 3600 <= t < t_tx + 72 * 3600 and st is not None and st[0] < 12]
                worst_stale.append(len(stale))
                firsts.append(first_fc(r, max(t_tx, t_rx)))
                shown_after.append(next((s[2] for s in r.series if s[0] >= t_tx + 6 * 3600 and s[2] is not None), None))
            rows.append((name, v2, sum(worst_stale), deadzone_sent, agg(firsts), agg(shown_after)))
    for name, v2, stale, dz, fst, shown in rows:
        info("G3", f"{name} [{'NOWY' if v2 else 'STARY'}]: probek ze starymi danymi (prognoza <12 dni po resecie TX) / wyslane 25.0 przed resetem / godz. do 1. prognozy [med/max] / ekran 6 h po resecie [cm raw]",
             f"{stale} / {dz} / {('-' if fst[0] is None else f'{fst[0]:.0f}/{fst[1]:.0f}')} h / {('-' if shown[0] is None else f'{shown[0]:.0f}')}")
    for name, v2, stale, dz, fst, shown in rows:
        if v2 and name.startswith("RX->TX (Twoj"):
            check("G3", "NOWY, Twoj workflow: zadnych starych danych w prognozie po resecie TX", stale == 0, f"{stale} probek")
            check("G3", "NOWY, Twoj workflow: RX pokazuje pusty zbiornik (raw >= 140) po resecie TX", shown[0] is not None and shown[0] >= 140, f"{shown[0]}")
            check("G3", "NOWY, Twoj workflow: pierwsza prognoza w < 3 h od resetu TX", fst[1] is not None and fst[1] <= 3, f"max {fst[1]}")
        if v2 and name.startswith("bez RESET RX"):
            check("G3", "NOWY, bez RESET RX (zapomniany): TX czyszczacy historie wystarcza - brak starych danych", stale == 0, f"{stale} probek")
        if v2 and name.startswith("TX->RX"):
            check("G3", "NOWY, odwrotna kolejnosc resetow: brak starych danych", stale == 0, f"{stale} probek")


# ---------- G4: straty pakietow ----------
def g4(n=10):
    res = {}
    for p in (0.3, 0.6):
        for label, v2 in (("STARY", False), ("NOWY", True)):
            av, me = [], []
            for seed in range(n):
                r = Run(seed=seed, days=20, v2=v2, tank_kw=dict(start_cm=150, rate=5, rate_var=0.2), sensor_kw=dict(sigma=0.6),
                        env_kw=dict(p_loss=p)).run()
                s = fc_stats(r, 6 * DAY, 20 * DAY, 5.0)
                av.append(s["avail"])
                me.append(s["med"])
            res[(p, label)] = (statistics.mean(av), statistics.median(me))
        info("G4", f"straty radia {int(p * 100)}%/kierunek, dni 6-20: dostepnosc / mediana bledu STARY | NOWY",
             f"STARY {res[(p, 'STARY')][0]:.0f}% / {pct(res[(p, 'STARY')][1])} | NOWY {res[(p, 'NOWY')][0]:.0f}% / {pct(res[(p, 'NOWY')][1])}")
    check("G4", "NOWY przy 30% strat: dostepnosc >= STARY i blad nie gorszy o > 3 pp",
          res[(0.3, "NOWY")][0] >= res[(0.3, "STARY")][0] - 1 and res[(0.3, "NOWY")][1] <= res[(0.3, "STARY")][1] + 0.03)


# ---------- G5: resety TX (utrata zasilania) i dryf RTC ----------
def g5(n=10):
    out = {}
    for label, v2 in (("STARY", False), ("NOWY", True)):
        av, me = [], []
        for seed in range(n):
            rng = random.Random(seed)
            ev = sorted((rng.uniform(5, 10) * DAY, None, False) for _ in range(3))
            r = Run(seed=seed, days=12, v2=v2, tank_kw=dict(start_cm=140, rate=5, rate_var=0.2), sensor_kw=dict(sigma=0.6), tx_power_events=ev).run()
            s = fc_stats(r, 5 * DAY, 11 * DAY, 5.0)
            av.append(s["avail"])
            me.append(s["med"])
        out[label] = (statistics.mean(av), statistics.median(me))
    info("G5", f"3 resety zasilania TX w dniach 5-10 ({n} przebiegow): dostepnosc / mediana bledu STARY | NOWY",
         f"STARY {out['STARY'][0]:.0f}% / {pct(out['STARY'][1])} | NOWY {out['NOWY'][0]:.0f}% / {pct(out['NOWY'][1])}")
    check("G5", "NOWY: reset TX bez wywozu nie kasuje prognozy (dostepnosc >= 97%, blad <= 15%)", out["NOWY"][0] >= 97 and out["NOWY"][1] <= 0.15,
          f"{out['NOWY'][0]:.0f}% / {pct(out['NOWY'][1])}")
    dr = {}
    for drift in (-0.05, 0.0, 0.05):
        me, p9 = [], []
        for seed in range(n):
            r = Run(seed=seed, days=14, v2=True, rtc_drift=drift, tank_kw=dict(start_cm=140, rate=5, rate_var=0.2), sensor_kw=dict(sigma=0.6)).run()
            s = fc_stats(r, 5 * DAY, 14 * DAY, 5.0)
            me.append(s["med"])
            p9.append(s["p90"])
        dr[drift] = (statistics.median(me), statistics.median(p9))
    info("G5", "NOWY: wplyw dryfu zegara RTC TX (czas liczony z zadanych snow) na blad prognozy [mediana | p90]",
         " ; ".join(f"{d:+.0%}: {pct(v[0])} | {pct(v[1])}" for d, v in dr.items()))
    check("G5", "NOWY: dryf RTC +-5% nie psuje prognozy (mediana <= 15%)", all(v[0] <= 0.15 for v in dr.values()), str({d: pct(v[0]) for d, v in dr.items()}))


# ---------- G6: testy jednostkowe RX v2 ----------
def pkt(epoch, seq, vals, step=21600, synth=()):
    """pakiet: najnowszy pierwszy; vals = lista raw od NAJNOWSZEGO"""
    return dict(epoch=epoch, seq=seq, pts=[(v, i * step, (i in synth)) for i, v in enumerate(vals)])


def g6():
    ep = 111
    # historia 14 pkt, spadek 1.25 cm / 6 h (5 cm/dobe) -> od razu zielona prognoza
    vals = [150 - 1.25 * (13 - i) for i in range(14)]
    vals = list(reversed([150 - 1.25 * (13 - i) for i in range(14)]))   # najnowszy (najnizszy) pierwszy
    vals = [100 + 1.25 * i for i in range(14)]                           # i=0 najnowszy = 100, starsze wyzej
    rx = R2.RxDevice2()
    rx.on_packet2(100.0, vals[0], pkt(ep, 50, vals))
    f = rx.forecast2()
    check("G6a", "pierwszy pakiet z 14 punktami -> od razu prognoza zielona z regresji", f is not None and f[3] == "green", str(f))
    true = (vals[0] - 10 - 15) / 5.0
    check("G6a", "wartosc prognozy bliska prawdy (5 cm/dobe)", f is not None and abs((f[0] + f[1]) / 2 - true) <= 1.5, f"{f} vs {true:.1f}")
    # pojedynczy punkt -> prior pomaranczowy
    rx1 = R2.RxDevice2()
    rx1.on_packet2(0.0, 155.0, pkt(7, 1, [155.0]))
    f1 = rx1.forecast2()
    check("G6b", "1 punkt po wywozie -> prior 6 cm/dobe, pomaranczowy", f1 is not None and f1[3] == "orange" and f1[0] == round((145 - 15) / 6.0), str(f1))
    # 7 punktow, rozpietosc 36 h -> zielona
    v7 = [150 - 1.0 * (6 - i) for i in range(7)]
    v7 = [150.0 - 1.0 * i for i in range(7)][::-1]
    v7 = [140.0 + 1.0 * i for i in range(7)]       # najnowszy 140 (i=0), starsze wyzej
    rx2 = R2.RxDevice2()
    rx2.on_packet2(0.0, v7[0], pkt(7, 7, v7))
    f2 = rx2.forecast2()
    check("G6b", "7 punktow / 36 h -> zielona (regresja)", f2 is not None and f2[3] == "green", str(f2))
    rx3 = R2.RxDevice2()
    v6 = v7[:6]
    rx3.on_packet2(0.0, v6[0], pkt(7, 6, v6))
    f3 = rx3.forecast2()
    check("G6b", "6 punktow / 30 h -> jeszcze pomaranczowa (prior)", f3 is not None and f3[3] == "orange", str(f3))
    # odciecie po RESET
    rx = R2.RxDevice2()
    rx.on_packet2(0.0, vals[0], pkt(ep, 50, vals))
    rx.manual_reset(10.0)
    check("G6c", "po RESET historia pusta i ekran 'waiting'", rx.screen == "waiting" and not rx.pts and rx.forecast2() is None)
    rx.on_packet2(20.0, vals[0], pkt(ep, 50, vals))        # powtorka starego pakietu
    check("G6c", "stary pakiet (seq <= odciecie) po RESET jest ignorowany", rx.screen == "waiting" and not rx.pts)
    rx.on_packet2(30.0, 155.0, pkt(ep, 51, [155.0] + vals[:13]))   # nowy seq, TX jeszcze nie wyczyscil historii
    check("G6c", "nowy seq: tylko punkty z seq > odciecia (1 punkt), reszta stara odrzucona", len(rx.pts) == 1 and rx.screen == "measure", f"{len(rx.pts)} pkt")
    rx.on_packet2(40.0, 156.0, pkt(999, 1, [156.0]))       # inna epoka (erase TX): zaakceptowana mimo seq=1 < 50
    check("G6d", "inna epoka (TX po erase, seq od 1) jest przyjmowana mimo odciecia", rx.lastepoch == 999 and rx.cut is None and len(rx.pts) == 1)
    # skok w historii (zabezpieczenie)
    rx = R2.RxDevice2()
    mixed = [100.0, 102.0, 104.0, 160.0, 105.0, 107.0]       # najnowszy pierwszy; skok 104->160? (starsze 160 > nowsze 104) = spadek; testujemy wzrost
    mixed = [160.0, 158.0, 100.0, 102.0, 104.0, 106.0]       # 158 -> 160 normalnie, ale 100 -> 158 = wzrost o 58 (wywoz) miedzy starszymi
    rx.on_packet2(0.0, mixed[0], pkt(ep, 9, mixed))
    check("G6e", "skok > 50 cm w odebranej historii odcina starsze punkty", len(rx.pts) == 2, f"{len(rx.pts)} pkt")
    # restart RX: blob NVS odtwarza prognoze od razu
    rx = R2.RxDevice2()
    rx.on_packet2(0.0, vals[0], pkt(ep, 50, vals))
    for h in range(1, 4):
        rx.tick(h * 3600.0)
    f_before = rx.forecast2()
    rx.power_on(3 * 3600.0 + 600)
    f_after = rx.forecast2()
    check("G6f", "po restarcie RX prognoza dostepna natychmiast (blob NVS) i zgodna z przed restartem",
          f_after is not None and f_before is not None and f_after[3] == "green" and abs(f_after[0] - f_before[0]) <= 1, f"przed {f_before} po {f_after}")
    # RESET przetrwa utrate zasilania: stary pakiet po restarcie nadal ignorowany
    rx.manual_reset(3 * 3600.0 + 700)
    rx.power_on(3 * 3600.0 + 800)
    rx.on_packet2(3 * 3600.0 + 900, vals[0], pkt(ep, 50, vals))
    check("G6g", "odciecie po RESET przezywa utrate zasilania RX", not rx.pts and rx.screen != "measure" or len(rx.pts) == 0, f"{len(rx.pts)} pkt")
    # syntetyczne 25.0 nie wchodzi do regresji
    rxs = R2.RxDevice2()
    vs = [25.0] + [100.0 + 1.25 * i for i in range(1, 14)]
    rxs.on_packet2(0.0, vs[0], pkt(ep, 60, vs, synth=(0,)))
    fs = rxs.forecast2()
    check("G6h", "punkt syntetyczny 25.0 (strefa martwa): prognoza 0 dni, nie psuje regresji", fs is not None and fs[0] == 0, str(fs))


# ---------- G7: brak regresji w warunkach usterek (jak E1) ----------
def g7(n=16, days=45):
    from t_e_e2e import fault_set, metrics
    res = {}
    for label, v2 in (("STARY", False), ("NOWY", True)):
        agg_ = []
        for seed in range(n):
            rng = random.Random(1000 + seed)
            pump = [rng.uniform(18, 30) * DAY]
            kw = dict(seed=seed, days=days, v2=v2, tank_kw=dict(start_cm=rng.uniform(80, 130), rate=rng.uniform(3, 8), pumpouts=pump),
                      sensor_kw=dict(faults=fault_set(rng, days), sigma=rng.uniform(0.3, 1.5)), rx_manual_resets=[pump[0] + 3600])
            agg_.append(metrics(Run(**kw).run()))
        res[label] = {k: statistics.mean(a[k] for a in agg_) for k in agg_[0]}
    o, nw = res["STARY"], res["NOWY"]
    info("G7", f"usterki jak E1 ({n} przebiegow x {days} dni): widok DOBRY / BLEDNY / falszywe 'pelny' h  STARY | NOWY",
         f"STARY {o['good']:.1f}% / {o['wrong']:.1f}% / {o['false_full_h']:.1f} h | NOWY {nw['good']:.1f}% / {nw['wrong']:.1f}% / {nw['false_full_h']:.1f} h")
    check("G7", "NOWY: widok pomiaru nie gorszy od STAREGO (DOBRY >= STARY - 1 pp)", nw["good"] >= o["good"] - 1.0, f"{nw['good']:.1f} vs {o['good']:.1f}")
    check("G7", "NOWY: falszywe 'pelny' nie wiecej niz STARY + 1 h/przebieg", nw["false_full_h"] <= o["false_full_h"] + 1.0, f"{nw['false_full_h']:.1f} vs {o['false_full_h']:.1f}")


def run():
    g6()
    g1()
    g1b()
    g2()
    g3()
    g3b()
    g4()
    g5()
    g7()
