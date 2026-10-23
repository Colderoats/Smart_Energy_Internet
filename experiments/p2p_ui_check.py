"""Headless-browser check of the prosumer login + dashboard (Chrome DevTools Protocol, same approach as market_ui_check.py).

    python experiments/p2p_ui_check.py --email home01@sei.local --password <password> [--base http://localhost:5173] [--shots <dir>]

Against a running backend + frontend + Hardhat node (demo run: PROSUMER_IRRADIANCE_OVERRIDE=800 MARKET_INTERVAL_SECONDS=30):
  logs in as a PROSUMER -> lands on /prosumer; admin URLs bounce back; admin API answers 403; the page shows the
  banner, role pill, net kW, balance; the card valid for the current role is enabled and the other is not; places an
  order (a sell offer in surplus, a buy bid in deficit); sees it queued, then in the live book, then watches the trade go
  pending/matched -> settled with a block number, and confirms the settle transaction on the Hardhat node (receipt status 1).
Exit code 1 if a check fails.
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
from ui_check import CDP, CHROME  # noqa: E402

RPC = "http://127.0.0.1:8545"
# my manual order (marked 'manual', building 'You') is in the live book while its interval is open
BOOK_JS = "[...document.querySelectorAll('[data-testid=book-table] tbody tr')].some(r=>/You/.test(r.innerText)&&/manual/.test(r.innerText))"


def receipt_status(tx: str):
    req = urllib.request.Request(RPC, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx]}).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req)).get("result")
    return None if not r else (int(r["status"], 16), int(r["blockNumber"], 16))


async def main(a) -> int:
    port = 9335
    prof = tempfile.mkdtemp()
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--window-size=1400,1500", "--disable-gpu", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
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
            await c.send("Emulation.setDeviceMetricsOverride", width=1400, height=1500, deviceScaleFactor=1, mobile=False)

            async def goto(url, settle=3.0):
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
                return errs

            def check(name, ok, detail=""):
                results.append((name, bool(ok), detail))
                print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

            setter = """const set=(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));};"""
            # ---- login -> /prosumer ----------------------------------------------------------
            await goto(f"{a.base}/login", 3)
            await js(f"""(async()=>{{{setter}const i=[...document.querySelectorAll('input')];set(i[0],{json.dumps(a.email)});set(i[1],{json.dumps(a.password)});
                document.querySelector('form').requestSubmit();}})()""")
            await asyncio.sleep(5)
            check("login lands on /prosumer", await js("location.pathname") == "/prosumer", await js("location.pathname"))
            await goto(f"{a.base}/dashboard/home", 3)
            check("admin dashboard URL bounces a prosumer back to /prosumer", await js("location.pathname") == "/prosumer", await js("location.pathname"))
            admin_status = await js("fetch('/nodes',{credentials:'same-origin'}).then(r=>r.status)")
            check("admin API answers 403 to the prosumer", admin_status == 403, str(admin_status))

            # ---- page content -------------------------------------------------------------
            await asyncio.sleep(3)
            head = await js("""({name:document.querySelector('[data-testid=building-name]')?.innerText,banner:document.querySelector('[data-testid=sim-banner]')?.innerText,
                role:document.querySelector('[data-testid=role-pill]')?.innerText,net:document.querySelector('[data-testid=net-kw]')?.innerText,
                balance:document.querySelector('[data-testid=balance]')?.innerText,live:/Live/.test(document.body.innerText)})""")
            print(json.dumps(head, ensure_ascii=False))
            check("header: building, role, net kW, balance", head["name"] and head["role"] in ("surplus", "deficit", "balanced") and "kW" in (head["net"] or "") and "demo credits" in (head["balance"] or ""), str(head))
            check("banner text", head["banner"] == "Simulated building: solar estimated from live weather, load synthetic. Amounts are demo credits.")
            check("live socket connected", head["live"])
            await shot("prosumer_dashboard")

            # ---- place an order with the card valid for the role ----------------------------------
            side = None
            for _ in range(40):  # wait until the role is surplus or deficit
                st = await js("""({sell:!document.querySelector('[data-testid=sell-kwh]').disabled,buy:!document.querySelector('[data-testid=buy-kwh]').disabled})""")
                if st["sell"] != st["buy"]:
                    side = "sell" if st["sell"] else "buy"
                    break
                await asyncio.sleep(3)
            check("exactly one order card is enabled (the one valid for the role)", side is not None, f"{side} {st}")
            if side is None:
                return 1
            rowjs = """[...document.querySelectorAll('[data-testid=trade-row]')].map(r=>{const c=[...r.querySelectorAll('td')].map(t=>t.innerText.trim());
                return {id:c[0],kwh:c[3],status:r.dataset.status,block:c[7],tx:(r.querySelector('button[aria-label]')?.title||'').split(': ')[1]||null}})"""
            base_ids = {r["id"] for r in await js(rowjs)}
            await js(f"""(()=>{{{setter}set(document.querySelector('[data-testid={side}-kwh]'),'0.01');}})()""")
            await asyncio.sleep(0.5)
            await js(f"document.querySelector('[data-testid={side}-submit]').click()")
            await asyncio.sleep(2.5)
            fb = await js(f"document.querySelector('[data-testid={side}-feedback]')?.innerText")
            check("order accepted (queued for the next interval)", fb and "Queued" in fb, str(fb))
            queued = await js("document.querySelectorAll('[data-testid=book-queued]').length")
            check("queued order shows in the book", queued == 1, str(queued))
            await shot("prosumer_order_queued")
            # the disabled card refuses nothing client-side, but the API refuses the wrong side too
            other = "bid" if side == "sell" else "offer"
            code = await js(f"fetch('/p2p/{other}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{kwh:0.01,{'max' if other == 'bid' else 'ask'}:6}})}}).then(r=>r.status)")
            check("API refuses the other side for this role (422)", code == 422, str(code))

            # ---- watch it become a trade and settle on chain -------------------------------------------
            seen, settled, mine, in_book = [], None, None, False
            for _ in range(80):
                in_book = in_book or await js(BOOK_JS)
                new = [r for r in await js(rowjs) if r["id"] not in base_ids]
                if mine is None:  # my order is the new trade of 0.010 kWh (auto orders are never exactly that)
                    mine = next((r["id"] for r in new if r["kwh"] == "0.010"), None)
                for r in new:
                    if r["id"] == mine and (not seen or seen[-1][1] != r["status"]):
                        seen.append((r["id"], r["status"]))
                done = [r for r in new if r["id"] == mine and r["status"] == "settled" and r["block"] not in (None, "—")]
                if done:
                    settled = done[0]
                    break
                await asyncio.sleep(3)
            print("trade statuses seen:", seen)
            check("my manual order was in the live book", in_book)
            check("trade reached 'settled' with a block number", settled, str(settled))
            await shot("prosumer_trade_settled")
            if settled and settled["tx"]:
                rc = receipt_status(settled["tx"])
                check("settle tx is mined on the Hardhat node (receipt status 1)", rc and rc[0] == 1, f"{settled['tx'][:14]}… block {rc[1] if rc else None} (page said {settled['block']})")
            else:
                check("settle tx hash visible", False)
            check("no console errors", not console_errors(), "; ".join(console_errors())[:300])
    finally:
        proc.terminate()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--base", default="http://localhost:5173")
    p.add_argument("--shots")
    sys.exit(asyncio.run(main(p.parse_args())))
