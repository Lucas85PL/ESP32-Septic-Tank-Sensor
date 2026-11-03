"""Uruchamia wszystkie symulacje i zapisuje wyniki do wyniki.md.   python run_all.py"""
import io, os, sys, contextlib, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tests"))
import common
import t_a_measurement, t_b_system, t_c_protocol, t_d_rx, t_e_e2e, t_f_fixes, t_g_history

buf = io.StringIO()
t0 = time.time()
for name, mod in (("A. Logika pomiarow TX", t_a_measurement), ("B. Maszyna stanow / energia / zasilanie TX", t_b_system),
                  ("C. Protokol logow TX<->RX", t_c_protocol), ("D. Odbiornik RX", t_d_rx), ("E. End-to-end Monte Carlo", t_e_e2e),
                  ("F. Weryfikacja rekomendowanych poprawek (symulator, firmware bez zmian)", t_f_fixes),
                  ("G. Propozycja v2: historia w TX + pakiet z historia + prior 6 cm/dobe (STARY vs NOWY)", t_g_history)):
    print(f"\n=== {name} ===")
    mod.run()
res = common.RESULTS
npass = sum(1 for r in res if r[2] is True); nfail = sum(1 for r in res if r[2] is False)
print(f"\nPODSUMOWANIE: PASS={npass} FAIL={nfail} INFO={sum(1 for r in res if r[2] is None)}  ({time.time()-t0:.1f}s)")
with open(os.path.join(HERE, "wyniki.md"), "w", encoding="utf-8") as f:
    f.write("# Wyniki symulacji (wygenerowane przez run_all.py)\n\n")
    f.write(f"PASS={npass}, FAIL={nfail}\n\n| ID | Test | Wynik | Szczegoly |\n|---|---|---|---|\n")
    for i, n, ok, d in res:
        f.write(f"| {i} | {n} | {'PASS' if ok else ('FAIL' if ok is False else 'info')} | {d} |\n")
