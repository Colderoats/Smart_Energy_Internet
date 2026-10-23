"""TC05 - dashboard during a fault. Needs the isolated stack (see tests/README.md): tests/tc05_server.py (8100), Hardhat node (8546),
tests/vite.tc05.config.mjs (5190), DB+admin from tests/tc05_setup_db.py. Run with any Python that has `playwright`:
    python tests/tc05_dashboard_fault.py [node_id]
Opens 5 dashboard views in 5 pages (each view has its own WebSocket), injects ONE fault, and records when each view first shows the
expected change (timestamps taken in the page). Screenshots before/after -> tests/screenshots/. Exit 1 if any view > 5 s."""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, LIMIT_MS = "http://localhost:5190", 5000
SHOTS = Path(__file__).parent / "screenshots"
EXE = r"C:\Users\deepa\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe"  # Chromium build present on this machine
NODE = sys.argv[1] if len(sys.argv) > 1 else "wind_scada_kelmarsh_2"
LABEL = {"wind_scada_kelmarsh_1": "Kelmarsh T1", "wind_scada_kelmarsh_2": "Kelmarsh T2", "wind_scada_kelmarsh_3": "Kelmarsh T3", "wind_scada_kelmarsh_4": "Kelmarsh T4"}[NODE]
# view -> (url, requirement, regex that must appear in the page text only AFTER the fault)
CHECKS = {
    "measurements": ("home", "measurements (KPIs + live alert for the faulted node)", rf"{LABEL}: Fault"),
    "fault_prediction": ("ai", "fault prediction view (AI Insights flags the node)", r"[1-9]\s+nodes?\s+flagged now"),
    "self_healing": ("map?view=twin", "self-healing action (twin decision log)", r"Curtailed to|Rerouted|Isolated"),
    "topology": ("map?view=twin", "topology view (faulted node state)", rf"FAULT \(replayed label\)"),
    "blockchain_log": ("chain", "blockchain log (record on chain)", rf"Rule-based detector flagged a fault on {NODE}"),
}
OBSERVER = """([key, pattern]) => { window.__hit = window.__hit || {};
  const re = new RegExp(pattern); const chk = () => { if (!window.__hit[key] && re.test(document.body.innerText)) window.__hit[key] = Date.now(); };
  new MutationObserver(chk).observe(document.body, {subtree: true, childList: true, characterData: true}); setInterval(chk, 50); }"""


def main():
    SHOTS.mkdir(exist_ok=True)
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=EXE)
        ctx = b.new_context(viewport={"width": 1500, "height": 950})
        lg = ctx.new_page(); lg.goto(f"{BASE}/login")
        lg.fill("input >> nth=0", "tc05@example.com"); lg.fill("input >> nth=1", "Tc05-test-password-1"); lg.click("button[type=submit]")
        lg.wait_for_url("**/dashboard/**", timeout=15000)
        pages = {}
        for key, (url, _, _) in CHECKS.items():
            q = ctx.new_page(); q.goto(f"{BASE}/dashboard/{url}"); pages[key] = q
        time.sleep(12)  # let sockets connect and the healthy feed tick

        def shot(q, name):  # reload so the React Flow canvas lays out (it does not in a background tab); state comes from /twin/nodes
            q.bring_to_front(); q.reload(); q.wait_for_timeout(4000)
            q.screenshot(path=str(SHOTS / name))

        for key, q in pages.items():
            shot(q, f"before_{key}.png")
        for key, q in pages.items():
            q.evaluate(OBSERVER, [key, CHECKS[key][2]])
        time.sleep(0.5)
        for key, q in pages.items():
            assert not q.evaluate("() => window.__hit && window.__hit['%s']" % key), f"{key}: expected change already present BEFORE the fault (no clean baseline)"
        pages["measurements"].bring_to_front()
        t0 = int(time.time() * 1000)
        req = urllib.request.Request(f"http://127.0.0.1:8100/_test/inject-fault?node_id={NODE}", method="POST", headers={"Origin": BASE})
        print("inject:", urllib.request.urlopen(req).read().decode(), f"(t0={t0})")
        time.sleep(LIMIT_MS / 1000 + 1.5)
        for key, q in pages.items():
            hit = q.evaluate("() => window.__hit['%s']" % key)
            results[key] = None if hit is None else hit - t0
        for key, q in pages.items():
            shot(q, f"after_{key}.png")
        b.close()
    bad = 0
    for key, ms in results.items():
        ok = ms is not None and ms <= LIMIT_MS
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {key:17s} {CHECKS[key][1]}: " + (f"updated {ms} ms after injection" if ms is not None else "NO UPDATE within window"))
    (SHOTS / "tc05_timings.json").write_text(json.dumps({"node": NODE, "limit_ms": LIMIT_MS, "first_seen_ms_after_injection": results}, indent=1))
    print("TC05", "PASS" if not bad else "FAIL")
    sys.exit(1 if bad else 0)


main()
