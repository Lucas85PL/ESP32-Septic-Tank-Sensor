"""Sweep parametrow dla iteracji 2 (V1 jako baza). Rejestracja wariantow na poziomie modulu (wymagane przez multiprocessing/Windows)."""
import sim2 as M
import sweep as W
from sim2 import V0, V1

NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", V0["name"], V1["name"]]
for pm in (8, 10, 15, 20):
    NAMES.append(W.reg(dict(V1, name=f"V1 pool_min={pm}", pool_min=pm)))
for ph in (1.5, 3.0):
    NAMES.append(W.reg(dict(V1, name=f"V1 pool_half={ph}", pool_half=ph)))
NAMES.append(W.reg(dict(V1, name="V1 + prior", prior=True)))
NAMES.append(W.reg(dict(V1, name="V1 + persist", persist=True)))
NAMES.append(W.reg(dict(V1, name="V1 + prior + persist", prior=True, persist=True)))

if __name__ == "__main__":
    res = M.run_all(NAMES, 300)
    W.show(res, NAMES)
