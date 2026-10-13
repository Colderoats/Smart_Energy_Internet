"""Experiment runner: one named config per paper table. Fixed seeds and the papers' iteration counts (journal 3 iterations; conference 5 datasets
for the fault classifier, 3 seeds for forecasting and FL).

    cd <repo>
    backend\\testbed\\venv\\Scripts\\python experiments\\run_all.py list
    backend\\testbed\\venv\\Scripts\\python experiments\\run_all.py run <config> [<config> ...]
    backend\\testbed\\venv\\Scripts\\python experiments\\run_all.py run all     # everything, in dependency order (hours; see docs)

Configs (each writes experiments/results/<run_id>/metrics.json):
  data         journal datasets: 3 train iterations + 3 held-out evaluation scenario sets per topology + the Table VIII scenario   (testbed/journal_sim.py)
  j_search     Table IV   25-epoch hyperparameter search (TA-GNN and GCN), all topologies, 3 iterations
  j_final      Table V    250-epoch training (3_LRS, 3_NLRS, 2_NLRS, GCN)
  j_tables456  Tables III-VI aggregation
  j_twin       Table VII/VIII/IX  twin vs default scheme on held-out scenarios and the 12-13 outage scenario
  j_fl         Table X    federated learning (grid on iteration 0, selected configs on iterations 0-2)
  j_trading    redistribution + EnergyMarket settlement per topology (needs a Hardhat node)
  j_contract   Table XI   gas / latency per operation (needs a Hardhat node)
  c_twin       conference Tables II, IV, V, Fig 2
  c_forecast   conference Table VII
  c_fl         conference Table VI
  c_contract   conference Table VIII (needs a Hardhat node)
  export       topologies.json, graphs.json, fault replays, KPIs, comparison.md
The grid / job farms run in parallel worker processes (--jobs N, default 10).
"""
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / "backend" / "testbed" / "venv" / "Scripts" / "python.exe")
BACK = ROOT / "backend"
TOPS, ITS = "ABC", (0, 1, 2)


def sh(cmd, cwd=ROOT, env_extra=None):
    import os
    env = dict(os.environ, PYTHONPATH=str(BACK))
    env.update(env_extra or {})
    print("$", " ".join(map(str, cmd)), flush=True)
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode:
        raise SystemExit(f"command failed: {cmd}")


def farm(cmds, jobs):
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(lambda c: sh(c), cmds))


def data(jobs):
    cmds = [[PY, "-m", "testbed.journal_sim", t, str(i), k] for k in ("train", "eval") for t in TOPS for i in ITS] + [[PY, "-m", "testbed.journal_sim", "C", "0", "c1213"]]
    farm([c for c in cmds], jobs)


def j_search(jobs):
    farm([[PY, "-m", "ai.testbed_models.train_journal", "search", t, str(i)] for t in TOPS for i in ITS], jobs)


def j_final(jobs):
    farm([[PY, "-m", "ai.testbed_models.train_journal", "final", t, str(i)] for t in TOPS for i in ITS], jobs)


def j_tables456(jobs):
    for c in ("t3", "t4_t5", "t6"):
        sh([PY, "experiments/journal_tables.py", c])


def j_twin(jobs):
    farm([[PY, "experiments/job_twin.py", t, str(i), "eval"] for t in TOPS for i in ITS] + [[PY, "experiments/job_twin.py", "C", "0", "c1213"]], jobs)
    sh([PY, "experiments/journal_tables.py", "t7_t8"])
    sh([PY, "experiments/journal_tables.py", "t9"])


def j_fl(jobs):
    sh([PY, "experiments/fl_runner.py", "grid", "--jobs", str(jobs)])
    sh([PY, "experiments/fl_runner.py", "final", "--jobs", str(jobs)])
    sh([PY, "experiments/fl_runner.py", "tables"])


def j_trading(jobs):
    for t in TOPS:
        for v in ("normal", "postfault"):
            sh([PY, "experiments/job_trading.py", t, v, "automine"])
        sh([PY, "experiments/job_trading.py", t, "normal", "interval"])
    sh([PY, "experiments/trading_tables.py"])


def j_contract(jobs):
    sh([PY, "experiments/contract_bench.py", "ops"])
    sh([PY, "experiments/trading_tables.py"])


def c_twin(jobs):
    sh([PY, "experiments/conf_tables.py", "twin"])


def c_forecast(jobs):
    sh([PY, "-m", "ai.testbed_models.train_conf", "forecast"], cwd=BACK, env_extra={"PYTHONPATH": str(BACK)})
    sh([PY, "experiments/conf_tables.py", "forecast"])


def c_fl(jobs):
    sh([PY, "-m", "ai.testbed_models.train_conf", "fl"], cwd=BACK, env_extra={"PYTHONPATH": str(BACK)})
    sh([PY, "experiments/conf_tables.py", "fl"])


def c_contract(jobs):
    sh([PY, "experiments/contract_bench.py", "conf"])


def export(jobs):
    sh([PY, "experiments/export_all.py"])
    sh([PY, "experiments/compare_all.py"])


ORDER = ["data", "j_search", "j_final", "j_tables456", "j_twin", "j_fl", "j_trading", "j_contract", "c_twin", "c_forecast", "c_fl", "c_contract", "export"]
FUNCS = {k: globals()[k] for k in ORDER}

if __name__ == "__main__":
    args = sys.argv[1:]
    jobs = 10
    if "--jobs" in args:
        i = args.index("--jobs")
        jobs = int(args[i + 1])
        del args[i:i + 2]
    if not args or args[0] == "list":
        print(__doc__)
        raise SystemExit
    names = ORDER if args[1:] == ["all"] else args[1:]
    for n in names:
        FUNCS[n](jobs)
