"""Przyklad: jeden przebieg ze scenariusza D (awaria odbiornika) - stara vs nowa logika, slot po slocie."""
import sim

sc = sim.SCENARIOS["D. Brak odbiornika (2 awarie 0.5-7 dni)"]
best = None
for seed in range(1, 101):
    w = sim.World(sc, seed)
    if not w.outages:
        continue
    mo = sim.metrics(sim.run_old(w, seed), w)
    ro = [x for x in mo["rec_out"] if x is not None]
    if ro and (best is None or max(ro) > best[0]):
        best = (max(ro), seed)
seed = best[1]
w = sim.World(sc, seed)
old, new = sim.run_old(w, seed), sim.run_new(w, seed)
a, b = min(o[0] for o in w.outages) / 24, max(o[1] for o in w.outages) / 24
print(f"Seed {seed}. Awarie odbiornika (dni): " + ", ".join(f"{x/24:.1f}-{y/24:.1f}" for x, y in w.outages))
print("Wywozy (dzien): " + ", ".join(f"{p:.1f}" for p in w.pumps))
print("\n dzien | prawda | odbiornik | STARA dostarczyla | NOWA dostarczyla")
print("-------+--------+-----------+-------------------+-----------------")
def cell(s):
    if s is None:
        return "-"
    if s["value"] is None:
        return "cisza (brak wyniku)"
    if not s["sent"]:
        return f"{s['value']:.0f} cm - brak ACK" + (" (retry)" if s["retry"] else "")
    return f"{s['value']:.0f} cm" + ("" if sim.is_correct(s) else "  <-- BLAD")
lo = a - 2
hi = lo + 22
for so in old:
    d = so["t_wake"] / 24
    if lo <= d <= hi:
        sn = min(new, key=lambda x: abs(x["t_wake"] - so["t_wake"]))
        rx = "OK" if w.rx_up(so["t_wake"]) else "BRAK"
        print(f" {d:5.1f} | {w.truth(so['t_wake']):6.0f} | {rx:9s} | {cell(so):17s} | {cell(sn)}")
