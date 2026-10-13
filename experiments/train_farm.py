"""Run every journal training fit (Tables IV and V) as an independent process, `--jobs` at a time, longest first; then merge the per-job files.

    python experiments/train_farm.py [--jobs 10]
Idempotent: a fit whose output file already exists is skipped.
"""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACK = ROOT / "backend"
PY = str(BACK / "testbed" / "venv" / "Scripts" / "python.exe")
ART = BACK / "ai" / "artifacts" / "testbed"
LOGS = BACK / "testbed" / "logs"
TOPS, ITS = "ABC", (0, 1, 2)
ENV = dict(os.environ, PYTHONPATH=str(BACK), PYTHONWARNINGS="ignore")


def out(top, it):
    return ART / f"journal_{top}" / f"it{it}"


def run(args, log):
    with open(LOGS / log, "a") as f:
        subprocess.run([PY, "-m", "ai.testbed_models.train_journal", *args], cwd=BACK, env=ENV, stdout=f, stderr=subprocess.STDOUT)


def ready(top, it):
    return (BACK / "testbed" / "data" / f"journal_{top}" / f"it{it}" / "manifest.json").exists()


def job(spec):
    kind, top, it, a, b = spec
    while not ready(top, it):
        time.sleep(30)
    if kind == "search":
        if not (out(top, it) / f"search_{a}_o{b}.json").exists():
            run(["search", top, str(it), a, str(b)], f"train_{top}_{it}_search_{a}{b}.log")
    elif a == "GCN":
        while not all((out(top, it) / f"search_gcn_o{o}.json").exists() for o in range(1, 5)):
            time.sleep(30)
        if not list(out(top, it).glob("final_gcn_*.json")):
            run(["final", top, str(it), "GCN"], f"train_{top}_{it}_final_GCN.log")
    elif not (out(top, it) / f"final_{a}.json").exists():
        run(["final", top, str(it), a], f"train_{top}_{it}_final_{a}.log")


def main(jobs):
    LOGS.mkdir(parents=True, exist_ok=True)
    specs = []
    for it in ITS:
        for top in TOPS:
            if top == 'C' and it > 0:
                continue  # amendment 4: topology C trains on iteration 0 only
            specs += [("final", top, it, n, 0) for n in ("3_LRS", "3_NLRS", "2_NLRS")]
            specs += [("search", top, it, k, o) for k in ("tag", "gcn") for o in range(1, 5)]
    specs += [("final", top, it, "GCN", 0) for it in ITS for top in TOPS if not (top == 'C' and it > 0)]  # last: they wait for their GCN searches
    cost = {"3_LRS": 250, "3_NLRS": 250, "2_NLRS": 150, "GCN": 250}
    specs.sort(key=lambda s: -(cost.get(s[3], 25) if s[0] == "final" else 25) + (1000 if s[3] == "GCN" else 0))
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(job, specs))
    for top in TOPS:
        for it in ITS:
            if top == 'C' and it > 0:
                continue
            run(["collect", top, str(it)], f"train_{top}_{it}_collect.log")
    print("training farm done", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 10)
