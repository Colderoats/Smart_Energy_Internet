"""Run ONE testbed federation over Flower gRPC: a server process plus one client process per grid node.

    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_testbed --top A --it 0 --mode fedprox_journal_adaptive --mu 0.01 --eta 5 --epochs 3 --target 0.0132 --rounds 60

Output: ai/artifacts/testbed/journal_<top>/it<it>/flower/<run>/{run_meta,round_log,wire_audit}.json + logs.
Memory: every client loads the windowed tensors (~140 MB for topology C), so this is practical for topologies A (6 clients) and B (14); topology C (33 processes)
is run with the in-process simulation (same local_train and the same weighting functions). PROVENANCE: simulated_testbed.
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ART = BACKEND / "ai" / "artifacts" / "testbed"
N_CLIENTS = {"A": 6, "B": 14, "C": 33}


def wait_port(port, timeout=120.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError(port)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", required=True)
    ap.add_argument("--it", type=int, default=0)
    ap.add_argument("--mode", required=True)
    ap.add_argument("--mu", type=float, default=0.0)
    ap.add_argument("--eta", type=float, default=0.0)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--target", type=float, required=True)
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--name")
    a = ap.parse_args()
    K = N_CLIENTS[a.top]
    name = a.name or f"{a.mode}_mu{a.mu:g}_eta{a.eta:g}_E{a.epochs}"
    out = ART / f"journal_{a.top}" / f"it{a.it}" / "flower" / name
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONWARNINGS": "ignore", "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(BACKEND)}
    py = sys.executable
    srv = subprocess.Popen([py, "-m", "ai.federated.server_testbed", "--mode", a.mode, "--mu", str(a.mu), "--eta", str(a.eta), "--epochs", str(a.epochs), "--clients", str(K),
                            "--target", str(a.target), "--rounds", str(a.rounds), "--port", str(a.port), "--out", str(out)],
                           cwd=BACKEND, env=env, stdout=open(out / "server.log", "w"), stderr=subprocess.STDOUT)
    clients = []
    try:
        wait_port(a.port)
        for k in range(K):
            clients.append(subprocess.Popen([py, "-m", "ai.federated.client_testbed", "--top", a.top, "--it", str(a.it), "--node", str(k), "--server", f"127.0.0.1:{a.port}"],
                                            cwd=BACKEND, env=env, stdout=open(out / f"client_{k}.log", "w"), stderr=subprocess.STDOUT))
        while srv.poll() is None:
            if any(p.poll() not in (None, 0) for p in clients):
                break
            time.sleep(1.0)
        if srv.poll() == 0:
            for p in clients:
                p.wait(timeout=120)
    finally:
        for p in [srv] + clients:
            if p.poll() is None:
                p.kill()
    if srv.returncode != 0:
        raise SystemExit(f"federation failed:\n{(out / 'server.log').read_text()[-1500:]}")
    print("ok", out)


if __name__ == "__main__":
    main()
