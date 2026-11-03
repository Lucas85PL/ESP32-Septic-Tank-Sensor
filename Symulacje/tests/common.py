import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "fw"))
sys.path.insert(0, os.path.join(ROOT, "env"))

RESULTS = []


def check(test_id, name, ok, detail=""):
    RESULTS.append((test_id, name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {test_id} {name}" + (f"  -> {detail}" if detail else ""))
    return ok


def info(test_id, name, detail):
    RESULTS.append((test_id, name, None, detail))
    print(f"[INFO] {test_id} {name}  -> {detail}")


def scripted_cycle(ref, gen, is_retry=False, seed=0, accept_rise_now=False):
    """uruchamia jeden cykl pomiarowy z generatorem gen(series, i, rng)->cm (<0 timeout)"""
    import tx_measurement as M
    rng = random.Random(seed)
    state = {"n": 0}

    def read():
        n = state["n"]
        state["n"] += 1
        return gen(n // M.MEAS_PER_SERIES, n % M.MEAS_PER_SERIES, rng)

    mm = M.MeasurementManager(read, lambda s: None, ref, is_retry, accept_rise_now)
    return mm.run_cycle()
