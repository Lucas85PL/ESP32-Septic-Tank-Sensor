import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import swarm.d_konsensus as D
import sim2 as S2
EXTRA = [
    D.mk("E1 min6 sup2", prior_min=6, sup_prior=2, sup_dom=2),
    D.mk("E2 min5 sup3", prior_min=5, sup_prior=3, sup_dom=3),
    D.mk("E3 min4 sup3", prior_min=4, sup_prior=3, sup_dom=3),
    D.mk("E4 min6 sup4", prior_min=6, sup_prior=4, sup_dom=4),
    D.mk("E5 min6 sup3 prior only", prior_min=6, sup_prior=3, sup_dom=1),
    D.mk("E6 min6 sup3 +-1.0", prior_min=6, sup_prior=3, sup_dom=3, half=1.0),
    D.mk("E7 min6 sup3 +-2.0", prior_min=6, sup_prior=3, sup_dom=3, half=2.0),
    D.mk("E8 min5 sup3 sd0.2 +-1.5", prior_min=5, sup_prior=3, sup_dom=3, sd_min=0.2),
    D.mk("E9 min6 sup3 vote", prior_min=6, sup_prior=3, sup_dom=3, mode="vote"),
]
for c in EXTRA:
    S2.register(c["name"], (lambda cfg: (lambda w, s: D.DLogic(cfg).run(w, s)))(c))
if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    names = ["V4 firmware (+-1.5, min12)", "D3 prior min6 + sup3", "D9 min6 + sup3 + sd>=0.2"] + [c["name"] for c in EXTRA]
    res = S2.run_all(names, runs)
    print(f"FAULTS={D.FAULTS} ECHO_P={D.ECHO_P} runs={runs}")
    print(S2.table(res, names))
