"""A. Logika pomiarow TX - przypadki brzegowe (jednostkowo, na wiernym porcie measurement.cpp)"""
from common import *   # noqa
import tx_measurement as M


def ref(value, valid=True, age=0, rej=0, dz=0):
    return M.RefState(value, valid, age, rej, dz)


def run():
    # A1 czysty pomiar
    r = ref(60.0)
    res = scripted_cycle(r, lambda s, i, g: 60 + g.gauss(0, 0.4))
    check("A1", "czysty pomiar -> OK ~60", res.status == M.OK and abs(res.value - 60) < 0.5, f"{res.status} {res.value:.2f}")

    # A2 odpornosc na szum (sloshing / zmarszczki): odsetek NO_VALID zaleznie od sigma
    out = []
    for sigma in (0.5, 1.5, 3.0, 5.0, 8.0, 12.0):
        bad = 0
        for k in range(200):
            r = ref(60.0, age=6 * 3600)
            res = scripted_cycle(r, lambda s, i, g: 60 + g.gauss(0, sigma), seed=k)
            bad += 0 if res.status == M.OK and abs(res.value - 60) < 4 else 1
        out.append((sigma, bad / 2))
    info("A2", "% cykli bez poprawnego wyniku vs sigma szumu [cm]", ", ".join(f"s={s}:{b:.0f}%" for s, b in out))
    check("A2", "sigma<=3 cm (rozsadne zmarszczki) -> <=2% cykli stracone", all(b <= 2 for s, b in out if s <= 3.0))

    # A3 50% timeoutow
    r = ref(60.0, age=6 * 3600)
    res = scripted_cycle(r, lambda s, i, g: -1 if g.random() < 0.5 else 60 + g.gauss(0, 0.5))
    check("A3", "50% timeoutow -> nadal OK", res.status == M.OK, res.status)

    # A4 tylko 20% probek prawdziwych, reszta losowa 25-170
    okc = 0
    for k in range(200):
        r = ref(60.0, age=6 * 3600)
        res = scripted_cycle(r, lambda s, i, g: 60 + g.gauss(0, 0.4) if g.random() < 0.2 else g.uniform(25, 170), seed=k)
        okc += res.status == M.OK and abs(res.value - 60) < 3
    check("A4", "20% prawdziwych + 80% losowych (ref znany) -> >=70% poprawnych", okc >= 140, f"{okc/2:.0f}%")

    # A5 wywoz: 2 kolejne zgodne cykle albo reset reczny TX
    r = ref(30.0, age=6 * 3600)
    r1 = scripted_cycle(r, lambda s, i, g: 160 + g.gauss(0, 0.5))
    r.secondsSinceRef += 6 * 3600
    r2 = scripted_cycle(r, lambda s, i, g: 161 + g.gauss(0, 0.5), seed=1)
    check("A5", "wywoz 30 -> 160: 1. cykl czeka na potwierdzenie, 2. zgodny cykl przyjmuje",
          r1.status == M.REJECTED_JUMP and r2.status == M.OK and r2.value > 150, f"{r1.status} -> {r2.status} {r2.value:.1f}")
    r = ref(30.0, age=86400)
    r3 = scripted_cycle(r, lambda s, i, g: 160 + g.gauss(0, 0.5), accept_rise_now=True)
    check("A5b", "wywoz po fizycznym resecie TX przyjety od razu", r3.status == M.OK and r3.value > 150, f"{r3.status}")
    r = ref(60.0, age=6 * 3600)
    scripted_cycle(r, lambda s, i, g: 150 + g.gauss(0, 0.5))
    r.secondsSinceRef += 6 * 3600
    r4 = scripted_cycle(r, lambda s, i, g: 59 + g.gauss(0, 0.5), seed=2)
    check("A5c", "kandydat na wywoz niepotwierdzony (kolejny cykl normalny) jest odrzucony i kasowany", r4.status == M.OK and r.risePending == 0, f"{r4.status} {r4.value:.1f}")
    r = ref(30.0, age=6 * 3600)
    scripted_cycle(r, lambda s, i, g: 160 + g.gauss(0, 0.5))
    r.secondsSinceRef += 6 * 3600
    r5 = scripted_cycle(r, lambda s, i, g: 120 + g.gauss(0, 0.5), seed=3)
    check("A5d", "dwa cykle niezgodne (160 potem 120) nie potwierdzaja wywozu", r5.status == M.REJECTED_JUMP, r5.status)

    # A6 falszywy "wywoz": stale echo 150 cm przez 1 cykl przy prawdziwych 60
    r = ref(60.0, age=6 * 3600)
    res = scripted_cycle(r, lambda s, i, g: 150 + g.gauss(0, 0.2))
    check("A6", "jednorazowe stabilne echo 150 cm (prawda 60) jest ODRZUCONE", not (res.status == M.OK),
          f"{res.status} {res.value:.1f}")

    # A6b czas powrotu po falszywym wywozie
    # A6b: echo 150 w dwoch kolejnych cyklach (czujnik wyjety na 12 h) - jedyna droga do falszywego wywozu
    r = ref(60.0, age=6 * 3600)
    st = []
    for c in range(2):
        st.append(scripted_cycle(r, lambda s, i, g: 150 + g.gauss(0, 0.2), seed=c).status)
        r.secondsSinceRef += 6 * 3600
    info("A6b", "czujnik wyjety na >= 12 h (stale 150 cm) -> falszywy wywoz nadal mozliwy po 2 cyklach", " -> ".join(st))

    # A7 strefa martwa - rozne zachowania czujnika
    def dz_run(gen, ref0=30.0):
        r = ref(ref0, age=0)
        reported = None
        for c in range(14):
            r.secondsSinceRef += 6 * 3600
            res = scripted_cycle(r, gen, seed=c)
            if res.status == M.BELOW_MIN_RANGE:
                reported = c + 1
                break
        return reported
    for name, gen in (("scatter 10-24 + 30% timeout", lambda s, i, g: g.uniform(10, 24) if g.random() < 0.7 else -1),
                      ("stabilne 22.0+-0.2", lambda s, i, g: 22 + g.gauss(0, 0.2)),
                      ("same timeouty", lambda s, i, g: -1),
                      ("40% <25, 60% timeout", lambda s, i, g: g.uniform(10, 24) if g.random() < 0.4 else -1)):
        rep = dz_run(gen)
        info("A7", f"strefa martwa [{name}]: cykl w ktorym TX wysle 25.0", "NIGDY" if rep is None else f"{rep}. cykl = {rep*6} h")
    rep_scatter = dz_run(lambda s, i, g: g.uniform(10, 24) if g.random() < 0.7 else -1)
    info("A7", "strefa martwa raportowana po 36 h, RX alarmuje po 25 h", f"raport po {rep_scatter*6 if rep_scatter else None} h  [ZAAKCEPTOWANE: wywoz jest organizowany przy zblizaniu sie do pelnego]")
    rep_stable = dz_run(lambda s, i, g: 22 + g.gauss(0, 0.2))
    info("A7b", "stabilne echo <25 cm / same timeouty w strefie martwej: TX milczy", "ZAAKCEPTOWANE (poziom <= 25 cm jest widoczny wczesniej jako ~25-30 cm)" if rep_stable is None else "raportuje")

    # A8 cold boot z odtworzonym ref + dlugi postoj: poziom urosl 40 cm
    r = ref(100.0, age=86400)           # po przywroceniu: +24h
    rej = 0
    oks = None
    for c in range(8):
        res = scripted_cycle(r, lambda s, i, g: 60 + g.gauss(0, 0.3), seed=c)
        if res.status == M.OK:
            oks = c + 1
            break
        r.secondsSinceRef += 6 * 3600
    info("A8", "po 'zimnym' starcie (ref 100, prawda 60): cykli do pierwszej wartosci", f"{oks}")

    # A9 bootstrap z dwoma rownymi klastrami
    r = ref(100.0, valid=False)
    res = scripted_cycle(r, lambda s, i, g: (60 if s < 3 else 100) + g.gauss(0, 0.3))
    check("A9", "bootstrap, dwa rowne klastry (30/30) -> brak wyniku (nie zgaduje)", res.status == M.NO_VALID, res.status)

    # A10 bootstrap z falszywym echem 25.4 dominujacym (60%) przy prawdzie 70
    r = ref(100.0, valid=False)
    res = scripted_cycle(r, lambda s, i, g: 25.4 + g.gauss(0, 0.15) if g.random() < 0.6 else 70 + g.gauss(0, 0.3))
    check("A10", "bootstrap z dominujacym falszywym echem 25.4 NIE staje sie odniesieniem", not (res.status == M.OK and res.value < 30),
          f"{res.status} {res.value:.1f}")

    # A11 granica POOL_MIN_SAMPLES: klaster 11 / 12 probek bez ref
    for n in (11, 12):
        r = ref(100.0, valid=False)
        vals = [60.0] * n + [100 + 5 * k for k in range(60 - n)]
        it = iter(vals)
        res = scripted_cycle(r, lambda s, i, g, it=it: next(it))
        info("A11", f"bootstrap: klaster dokladnie {n} probek", res.status)

    # A12 skok w dol (napelnianie) wiekszy niz okno: 4 odrzucenia i akceptacja
    r = ref(100.0, age=6 * 3600)
    seq = []
    for c in range(7):
        res = scripted_cycle(r, lambda s, i, g: 40 + g.gauss(0, 0.3), seed=c)
        seq.append(res.status)
        r.secondsSinceRef += 6 * 3600 if res.status != M.OK else 0
    info("A12", "skok 100->40 (poza oknem 15cm/d): sekwencja statusow", " ".join(seq))
