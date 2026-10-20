"""Headless-browser check of the live prosumer market views (Chrome DevTools Protocol, same approach as ui_check.py).

    python experiments/market_ui_check.py --email <admin email> --password <password> [--base http://localhost:5173] [--shots <dir>]

Checks, against a running backend + frontend (+ Hardhat node):
  Digital Twin  : prosumer cards, SURPLUS/DEFICIT pills, provenance badges, "On-chain ✓ #block" chips,
                  trade edges (dashed while pending, solid + "Settled · block #N" once settled), market strip,
                  prosumer side panel (24 h chart, on-chain address).
  Redistribution: market summary card, Blockchain "Prosumer market" section (registrations table, order book, trade
                  journey with Mirrored-to-ledger step), "Market events" filter, trades table Source column.
  Every view: no console errors / exceptions (a 401 before login is ignored: events are cleared after login).
Exit code 1 if a check fails. Screenshots go to --shots.
"""
import argparse
import asyncio
import base64
import json
import sys
import tempfile
import time
import urllib.request
import subprocess
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).parent))
from ui_check import CDP, CHROME, VIEWS  # noqa: E402


async def main(a) -> int:
    port = 9334
    prof = tempfile.mkdtemp()
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--window-size=1700,1500", "--disable-gpu", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results: list[tuple[str, bool, str]] = []
    try:
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except Exception:
                time.sleep(0.5)
        page = next(t for t in tabs if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            c = CDP(ws)
            asyncio.create_task(c.reader())
            for d in ("Page", "Runtime", "Log", "Network"):
                await c.send(f"{d}.enable")
            await c.send("Emulation.setDeviceMetricsOverride", width=1700, height=1500, deviceScaleFactor=1, mobile=False)

            async def goto(url, settle=4.0):
                c.events.clear()
                await c.send("Page.navigate", url=url)
                await asyncio.sleep(settle)

            async def js(expr):
                r = await c.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                return r.get("result", {}).get("value")

            async def shot(name):
                if a.shots:
                    Path(a.shots).mkdir(parents=True, exist_ok=True)
                    s = await c.send("Page.captureScreenshot", format="png")
                    (Path(a.shots) / f"{name}.png").write_bytes(base64.b64decode(s["data"]))

            def console_errors():
                errs = []
                for e in c.events:
                    if e["method"] == "Runtime.exceptionThrown":
                        errs.append("exception: " + json.dumps(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:300])
                    elif e["method"] == "Runtime.consoleAPICalled" and e["params"]["type"] == "error":
                        errs.append("console.error: " + " ".join(str(x.get("value", x.get("description", ""))) for x in e["params"]["args"])[:300])
                    elif e["method"] == "Log.entryAdded" and e["params"]["entry"]["level"] == "error":
                        errs.append("log: " + e["params"]["entry"]["text"][:200] + " " + e["params"]["entry"].get("url", ""))
                return errs

            def check(name, ok, detail=""):
                results.append((name, bool(ok), detail))

            await goto(f"{a.base}/login", 3)
            await js(f"""(async()=>{{const set=(el,v)=>{{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{{bubbles:true}}));}};
                const i=[...document.querySelectorAll('input')];set(i[0],{json.dumps(a.email)});set(i[1],{json.dumps(a.password)});
                document.querySelector('form').requestSubmit();}})()""")
            await asyncio.sleep(5)

            # ---- Digital Twin -------------------------------------------------
            await goto(f"{a.base}/dashboard/map?view=twin", 14)
            info = await js("""(()=>{const t=document.body.innerText;const nodes=[...document.querySelectorAll('.react-flow__node')];
              const pro=nodes.filter(n=>/rooftop PV/.test(n.innerText));
              const edges=[...document.querySelectorAll('.react-flow__edge')].map(e=>e.getAttribute('data-testid')||e.getAttribute('data-id')||e.id||'');
              return {prosumers:pro.length,surplus:(t.match(/SURPLUS/g)||[]).length,deficit:(t.match(/DEFICIT/g)||[]).length,balanced:(t.match(/BALANCED/g)||[]).length,
                est:/Estimated solar · live weather/.test(t),demo:/Demo irradiance/.test(t),sim:(t.match(/Simulated load/g)||[]).length,
                onchain:(t.match(/On-chain ✓ #\\d+/g)||[]),strip:/Prosumer market/.test(t)&&/Interval #/.test(t),note:/simulated buildings/.test(t),
                tradeEdges:edges.filter(x=>x.includes('edge-trade-')).length,gridEdges:edges.filter(x=>x.includes('edge-grid-')).length,
                tradeLabels:(t.match(/[\\d.]+ kWh · (?:pending|Settled · block #\\d+)/g)||[]),
                dashed:[...document.querySelectorAll('.react-flow__edge path')].filter(p=>p.style.strokeDasharray&&p.style.strokeDasharray!=='none').length}})()""")
            print(json.dumps(info, indent=1, ensure_ascii=False))
            check("twin: 4 prosumer cards", info["prosumers"] == 4, str(info["prosumers"]))
            check("twin: role pills", info["surplus"] + info["deficit"] + info["balanced"] >= 4, f"{info['surplus']}S/{info['deficit']}D/{info['balanced']}B")
            check("twin: provenance badges", (info["est"] or info["demo"]) and info["sim"] >= 4, f"est={info['est']} demo={info['demo']} sim={info['sim']}")
            check("twin: on-chain chips", len(info["onchain"]) >= 4, str(info["onchain"]))
            check("twin: market strip + label", info["strip"] and info["note"])
            check("twin: trade edges", info["tradeEdges"] >= 1, f"{info['tradeEdges']} edges, labels {info['tradeLabels']}")
            await shot("digital_twin_prosumers")
            # a trade edge turns solid and reads "Settled · block #N" right after the interval settles: wait for one (up to 2 intervals)
            settled_label = None
            for _ in range(60):
                settled_label = await js("(document.body.innerText.match(/[\\d.]+ kWh · Settled · block #\\d+/)||[null])[0]")
                if settled_label:
                    break
                await asyncio.sleep(2)
            check("twin: settled edge reads 'Settled · block #N'", settled_label, str(settled_label))
            await shot("digital_twin_settled_edge")
            # select a prosumer -> side panel
            await js("""(()=>{const n=[...document.querySelectorAll('.react-flow__node')].find(n=>/School/.test(n.innerText)&&/rooftop PV/.test(n.innerText));n&&n.querySelector('div').click()})()""")
            await asyncio.sleep(3)
            panel = await js("document.body.innerText")
            check("twin: prosumer side panel", "last 24 h" in panel.lower() and "generation vs consumption" in panel.lower() and "on-chain" in panel.lower())
            await shot("digital_twin_prosumer_panel")
            check("twin: no console errors", not console_errors(), "; ".join(console_errors())[:300])

            # ---- Redistribution / Blockchain ------------------------------------
            await goto(f"{a.base}/dashboard/chain", 10)
            t = await js("document.body.innerText")
            check("chain: market summary card", "Prosumer market (live)" in t and "prosumers registered on chain" in t)
            check("chain: live-market flow card", "Live market trade" in t and "Settled on chain · block #" in t)
            check("chain: Source column", "Live market" in t and "Source" in t)
            await shot("redistribution_summary")
            await js("""(()=>{[...document.querySelectorAll('button')].find(b=>/^Prosumer market$/.test(b.innerText.trim()))?.click()})()""")
            await asyncio.sleep(3)
            m = await js("""(()=>({reg:document.querySelectorAll('[data-testid=registration-row]').length,orders:document.querySelectorAll('[data-testid=order-row]').length,
               trades:document.querySelectorAll('[data-testid=trade-row]').length,journey:!!document.querySelector('[data-testid=trade-journey]'),
               text:document.body.innerText}))()""")
            tx = m["text"]
            check("market: 4 registrations", m["reg"] == 4, str(m["reg"]))
            check("market: order book", m["orders"] >= 1 and "offers" in tx.lower() and "bids" in tx.lower(), f"{m['orders']} orders")
            check("market: trade journey", m["journey"] and all(s in tx for s in ("Registered", "Offer", "Bid", "Matched", "Metered", "Settled", "Mirrored to ledger")))
            await js("""(()=>{document.querySelector('[data-testid=prosumer-market-panel]')?.scrollIntoView()})()""")
            await shot("blockchain_prosumer_market")
            # open the mirrored ledger record from the journey (pick a settled trade first)
            await js("""(()=>{[...document.querySelectorAll('[data-testid=trade-row]')].find(b=>/Settled/.test(b.innerText))?.click()})()""")
            await asyncio.sleep(1)
            await js("""(()=>{[...document.querySelectorAll('button')].find(b=>/P2P_TRADE #\\d+/.test(b.innerText))?.click()})()""")
            await asyncio.sleep(3)
            rec = await js("document.body.innerText")
            check("market: journey opens the ledger record (7-step + Verify)", "Verify integrity" in rec and "Live market" in rec)
            await shot("blockchain_ledger_record")
            await js("""(()=>{[...document.querySelectorAll('button')].find(b=>/Market events/.test(b.innerText))?.click()})()""")
            await asyncio.sleep(2)
            feed = await js("""(()=>({n:document.querySelectorAll('[data-testid=market-event-feed] li').length,t:document.body.innerText}))()""")
            check("market: Market events filter", feed["n"] >= 4 and "Settled" in feed["t"] and "Matched" in feed["t"], f"{feed['n']} events")
            await shot("blockchain_market_events")
            # deep link from the on-chain chip
            await goto(f"{a.base}/dashboard/chain?registration=prosumer_shop_01", 8)
            deep = await js("document.body.innerText")
            check("market: registration deep link", "Registered prosumers" in deep)
            check("chain: no console errors", not console_errors(), "; ".join(console_errors())[:300])

            # ---- every view still renders without console errors -----------------
            for v in VIEWS:
                await goto(f"{a.base}/dashboard/{v}", 5)
                text = await js("document.body.innerText")
                errs = console_errors()
                check(f"view {v}: renders, no console errors", len(text or "") > 40 and not errs, "; ".join(errs)[:300])

    finally:
        proc.kill()
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--shots")
    sys.exit(asyncio.run(main(ap.parse_args())))

