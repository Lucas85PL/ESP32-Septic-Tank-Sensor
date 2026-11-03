import sys
import sim2 as M
import sweep as W
from sim2 import V0, V1

V2 = dict(V1, name="V2 klastry+prior+persist", prior=True, persist=True, pool_half=1.5)
EXT = [1800, 1800, 1800, 3600, 3600, 7200, 7200]
V3 = dict(V2, name="V3 (rekomendowana)", retry=EXT, remeasure=True)
for c in (V2, V3):
    W.reg(c)
NAMES = ["SUFIT (idealny czujnik)", "1.4.5 (v1.5.0)", V0["name"], V1["name"], V2["name"], V3["name"]]

if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    res = M.run_all(NAMES, runs)
    out = f"# Symulacja 2 - iteracje logiki (50 dni, {runs} przebiegow na wariant)\n\n"
    out += "Punkt startowy iteracji: TX 1.4.7 (V0). V1: klastry probek zamiast konsensusu serii; "
    out += "V2: + wybor klastra zgodnego z oczekiwanym zakresem (prior) + odniesienie w flash po resecie TX; "
    out += "V3: + rozszerzone ponawianie wysylki z ponownym pomiarem.\n\n"
    out += M.table(res, NAMES) + "\n"
    print(out)
    open("wyniki2.md", "w", encoding="utf-8").write(out)
