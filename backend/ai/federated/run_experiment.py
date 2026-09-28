"""Runs ONE federated experiment end to end: a Flower server process plus one
client process per turbine, then the offline test evaluation.

    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_experiment --strategy fedprox_adaptive --mu 0.01 --seed 0
    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_experiment --strategy fedavg --scenario corrupted_update --seed 1 --rounds 5

Output directory (default ai/federated/artifacts/runs/<strategy>[_mu<mu>]_<scenario>_s<seed>/):
weights_{init,best,final}.npz, round_log.json (per-round per-client adaptive
weights, factors, update norms, reported scalars), run_meta.json, wire_audit.json,
result.json (test metrics), server.log, client_T*.log.

Everything is REAL replayed Kelmarsh SCADA; anything injected by --scenario is
SIMULATED and labelled so in the logs, run_meta.json and result.json.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
RUNS_DIR = Path(__file__).resolve().parent / "artifacts" / "runs"


def run_name(strategy: str, mu: float, scenario: str, seed: int) -> str:
    mu_part = f"_mu{mu:g}" if strategy != "fedavg" else ""
    return f"{strategy}{mu_part}_{scenario}_s{seed}"


def _wait_port(port: int, timeout: float = 90.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError(f"server did not open port {port}")


def run_federation(strategy: str, mu: float, seed: int, scenario: str, rounds: int, out_dir: Path, port: int, timeout: float = 3600) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONWARNINGS": "ignore", "PYTHONUNBUFFERED": "1"}
    py = sys.executable
    srv_log = open(out_dir / "server.log", "w")
    server = subprocess.Popen(
        [py, "-m", "ai.federated.server", "--strategy", strategy, "--mu", str(mu), "--seed", str(seed), "--rounds", str(rounds),
         "--scenario", scenario, "--port", str(port), "--out", str(out_dir)],
        cwd=BACKEND_DIR, env=env, stdout=srv_log, stderr=subprocess.STDOUT,
    )
    clients = []
    try:
        _wait_port(port)
        for t in (1, 2, 3, 4):
            log = open(out_dir / f"client_T{t}.log", "w")
            clients.append((subprocess.Popen(
                [py, "-m", "ai.federated.client", "--turbine", str(t), "--server", f"127.0.0.1:{port}", "--scenario", scenario, "--seed", str(seed)],
                cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT), log))
        t0 = time.time()
        while server.poll() is None:  # if the server dies, do not leave clients waiting for it
            if any(p.poll() not in (None, 0) for p, _ in clients) or time.time() - t0 > timeout:
                break
            time.sleep(1.0)
        if server.poll() == 0:
            for p, _ in clients:
                p.wait(timeout=120)
    finally:
        for p in [server] + [p for p, _ in clients]:
            if p.poll() is None:
                p.kill()
        srv_log.close()
        for _, log in clients:
            log.close()
    if server.returncode != 0 or any(p.returncode != 0 for p, _ in clients):
        tail = (out_dir / "server.log").read_text()[-1500:]
        raise RuntimeError(f"federation run failed (server rc={server.returncode}, clients rc={[p.returncode for p, _ in clients]}):\n{tail}")


def run_one(strategy: str, mu: float, seed: int, scenario: str = "clean", rounds: int = 30, port: int = 8098, out_dir: Path | None = None, force: bool = False) -> dict:
    from ai.federated import evaluate  # imported lazily: needs the eval bundle

    out_dir = Path(out_dir) if out_dir else RUNS_DIR / run_name(strategy, mu, scenario, seed)
    if (out_dir / "result.json").exists() and not force:
        return json.loads((out_dir / "result.json").read_text())
    t0 = time.time()
    run_federation(strategy, mu, seed, scenario, rounds, out_dir, port)
    result = evaluate.evaluate_run(out_dir)
    d = result["selected"]["full_view"]["detection"]
    print(f"  {out_dir.name}: {time.time() - t0:.0f}s  round {result['selected_round']}  full-view test F1={d['f1']:.3f} PR-AUC={d['pr_auc']:.4f}", flush=True)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, choices=["fedavg", "fedprox", "fedprox_adaptive"])
    ap.add_argument("--mu", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scenario", default="clean")
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--port", type=int, default=8098)
    ap.add_argument("--out")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    run_one(a.strategy, a.mu, a.seed, a.scenario, a.rounds, a.port, a.out, a.force)
