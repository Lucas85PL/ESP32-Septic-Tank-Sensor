"""C. Protokol logow TX->RX: kompletnosc, dokladnie-raz, zawieszenia, reset w trakcie transferu"""
from common import *   # noqa
import protocol as P


def make(seed=1, nrec=20, size=(2500, 4800)):
    rng = random.Random(seed)
    st = P.TxStore(rng)
    st.begin()
    for _ in range(nrec):
        st.commit(bytes(rng.randint(*size)))
    return st, P.RxTxLog(), rng


def drain(st, rx, ch, wakes=50, budget=20.0):
    total_t = 0.0
    for w in range(wakes):
        clk = {"t": 0.0}
        P.flush(st, rx, ch, clk, budget)
        total_t = max(total_t, clk["t"])
        if st.next_unsent() is None:
            return w + 1, total_t
    return None, total_t


def run():
    # C1 przeplyw bez strat
    st, rx, rng = make()
    ch = P.Channel(rng, 0.0)
    w, t = drain(st, rx, ch)
    check("C1", "bez strat: 20 rekordow dostarczone, kolejnosc, brak duplikatow",
          st.next_unsent() is None and [i for _, i, _ in rx.files] == sorted(st.records), f"wybudzen={w}, czas={t:.1f}s")

    # C2 przebieg strat: dostarczanie dokladnie raz (p = strata pakietu w JEDNYM kierunku, bez retransmisji MAC)
    for p in (0.05, 0.1, 0.2, 0.3, 0.5):
        st, rx, rng = make(seed=int(p * 100) + 1)
        ch = P.Channel(rng, p)
        w, t = drain(st, rx, ch, wakes=200)
        ids = [i for _, i, _ in rx.files]
        exact = ids == sorted(set(ids)) and set(ids) <= set(st.records)
        done = len(set(ids)) / 20.0
        if p <= 0.2:
            check("C2", f"p_loss={p:.2f}: wszystkie rekordy dostarczone dokladnie raz", exact and w is not None,
                  f"wybudzen do oproznienia={w}, max czas flush={t:.1f}s")
        else:
            info("C2", f"p_loss={p:.2f}: po 200 wybudzeniach dostarczono {done*100:.0f}% rekordow (bez duplikatow: {exact})",
                 f"TX zawsze zaczyna rekord od porcji 0 - przy ~18 porcjach/rekord szansa 'calosc w jednym wybudzeniu' maleje wykladniczo")
    # C3 tresc zgodna bajt w bajt
    st, rx, rng = make(seed=7, nrec=5)
    for k in st.records:
        st.records[k] = bytes((k * 7 + j) % 251 for j in range(len(st.records[k])))
    ch = P.Channel(rng, 0.15)
    drain(st, rx, ch, wakes=100)
    same = all(rx_data == st.records[i] for _, i, rx_data in rx.files)
    check("C3", "tresc rekordow identyczna bajt w bajt (p_loss=0.15)", same and len(rx.files) == 5)

    # C4 RX restartuje sie w srodku rekordu
    st, rx, rng = make(seed=8, nrec=3)
    ch = P.Channel(rng, 0.0)
    clk = {"t": 0.0}
    cid = st.next_unsent()
    # nadaj polowe rekordu recznie
    data = st.records[cid]
    total = (len(data) + 223) // 224
    for seq in range(total // 2):
        rx.handle_chunk(st.meta["epoch"], cid, seq, total, data[seq * 224:(seq + 1) * 224])
    rx.reboot()
    w, t = drain(st, rx, ch)
    check("C4", "reboot RX w polowie rekordu -> rekord dostarczony od nowa", len(rx.files) == 3, f"rekordow={len(rx.files)}")

    # C5 RX z pelnym dyskiem
    st, rx, rng = make(seed=9, nrec=3)
    rx.disk_full = True
    ch = P.Channel(rng, 0.0)
    w, t = drain(st, rx, ch, wakes=3)
    info("C5", "dysk RX pelny: wybudzen bez postepu, max czas flush", f"{w}, {t:.1f}s")
    check("C5", "dysk RX pelny nie blokuje TX dluzej niz budzet", t <= P.LOG_SYNC_BUDGET_S + 1)
    rx.disk_full = False
    w, t = drain(st, rx, ch)
    check("C5b", "po zwolnieniu miejsca na RX nadrabia zaleglosci", len(rx.files) == 3)

    # C6 zmiana epoki TX (kasowanie flash) - RX nie moze uznac nowych rekordow za duplikaty
    st, rx, rng = make(seed=10, nrec=5)
    ch = P.Channel(rng, 0.0)
    drain(st, rx, ch)
    st2 = P.TxStore(random.Random(99))
    st2.begin()
    for _ in range(3):
        st2.commit(bytes(3000))
    drain(st2, rx, ch)
    check("C6", "po nowej epoce TX (id znow od 1) RX przyjmuje rekordy", len(rx.files) == 8, f"{len(rx.files)}/8")

    # C7 RX zgubil NVS (kasowanie NVS), TX pamieta sentId -> brak nieskonczonej petli
    st, rx, rng = make(seed=11, nrec=4)
    drain(st, rx, P.Channel(rng, 0.0))
    rx.nvs = (False, 0, 0)
    st.meta["sentId"] = 0
    w, t = drain(st, rx, P.Channel(rng, 0.0))
    info("C7", "RX bez NVS + TX ponownie wysyla wszystko: rekordow w pliku RX (duplikaty)", len(rx.files))

    # C8 budzet czasu: nawet przy stratach 60% pojedynczy flush <= budzet + 1 porcja
    st, rx, rng = make(seed=12, nrec=28, size=(7000, 8200))
    ch = P.Channel(rng, 0.6)
    clk = {"t": 0.0}
    P.flush(st, rx, ch, clk, 20.0)
    check("C8", "flush ograniczony budzetem czasu", clk["t"] <= 20.0 + 3 * P.LOG_CHUNK_ACK_TIMEOUT_S + 0.5, f"{clk['t']:.1f}s")

    # C9 opoznione ACK (RX zajety przerysowaniem 0.5 s po pomiarze): ile marnuje TX
    st, rx, rng = make(seed=13, nrec=1)
    ch = P.Channel(rng, 0.0, rx_busy_s=0.5)
    clk = {"t": 0.0}
    P.flush(st, rx, ch, clk)
    info("C9", "RX zajety 0.5 s po pakiecie pomiaru: czas wysylki 1 rekordu / porcji wyslanych", f"{clk['t']:.2f}s / {ch.chunks_sent}")
    check("C9", "opoznione ACK nie psuje dostarczenia", len(rx.files) == 1)
