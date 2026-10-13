"""Launch the journal training chain (Table IV search, then Table V final) for every training dataset as soon as it exists.

    python experiments/train_watch.py            # runs until all 9 chains have been launched (A/B/C x iterations 0-2)
Pure convenience around `run_all.py j_search/j_final`; each chain writes backend/testbed/logs/train_<T>_<it>.log.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACK = ROOT / "backend"
PY = str(BACK / "testbed" / "venv" / "Scripts" / "python.exe")
started = {("A", 0), ("A", 1), ("A", 2)} if "--skip-A" in sys.argv else set()
jobs = [(t, i) for t in "ABC" for i in range(3)]
while len(started) < len(jobs):
    for t, i in jobs:
        if (t, i) in started:
            continue
        if (BACK / "testbed" / "data" / f"journal_{t}" / f"it{i}" / "manifest.json").exists():
            log = open(BACK / "testbed" / "logs" / f"train_{t}_{i}.log", "w")
            subprocess.Popen(f'"{PY}" -m ai.testbed_models.train_journal search {t} {i} && "{PY}" -m ai.testbed_models.train_journal final {t} {i}', shell=True,
                             cwd=BACK, env={**__import__("os").environ, "PYTHONPATH": str(BACK)}, stdout=log, stderr=subprocess.STDOUT)
            started.add((t, i))
            print("launched", t, i, flush=True)
    time.sleep(20)
