"""Headless-browser check of the dashboard views (Chrome DevTools Protocol; no extra dependency beyond `websockets`, which web3 already installs).

    python experiments/ui_check.py --base http://localhost:5173 --email <admin email> --password <password> [--shots <dir>]
Logs in through the real login page, opens every view (existing ones and the three new ones), waits for it to settle and reports console errors,
uncaught exceptions, failed /testbed + API requests and the text found in the page. Exit code 1 if anything is wrong.
"""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = next((p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)
VIEWS = ["home", "map", "sources", "chain", "ai", "analytics", "results", "topologies", "settings"]
EXPECT = {"results": "Paper target", "topologies": "Redistribution playback"}


class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.waiting, self.events = ws, 0, {}, []

    async def send(self, method, **params):
        self.n += 1
        i = self.n
        fut = asyncio.get_running_loop().create_future()
        self.waiting[i] = fut
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        return await fut

    async def reader(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.waiting:
                self.waiting.pop(m["id"]).set_result(m.get("result", m.get("error")))
            else:
                self.events.append(m)


async def main(a):
    port = 9333
    prof = tempfile.mkdtemp()
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--window-size=1500,1000", "--disable-gpu", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            problems, report = [], {}

            async def goto(url, settle=4.0):
                c.events.clear()
                await c.send("Page.navigate", url=url)
                await asyncio.sleep(settle)

            async def js(expr):
                r = await c.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
                return r.get("result", {}).get("value")

            await goto(f"{a.base}/login", 3)
            await js(f"""(async()=>{{const set=(el,v)=>{{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{{bubbles:true}}));}};
                const i=[...document.querySelectorAll('input')];set(i[0],{json.dumps(a.email)});set(i[1],{json.dumps(a.password)});
                document.querySelector('form').requestSubmit();}})()""")
            await asyncio.sleep(5)
            for v in VIEWS:
                await goto(f"{a.base}/dashboard/{v}", 6)
                text = await js("document.body.innerText")
                errs = []
                for e in c.events:
                    if e["method"] == "Runtime.exceptionThrown":
                        errs.append("exception: " + json.dumps(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:300])
                    elif e["method"] == "Runtime.consoleAPICalled" and e["params"]["type"] in ("error",):
                        errs.append("console.error: " + " ".join(str(x.get("value", x.get("description", ""))) for x in e["params"]["args"])[:300])
                    elif e["method"] == "Log.entryAdded" and e["params"]["entry"]["level"] == "error":
                        errs.append("log: " + e["params"]["entry"]["text"][:200] + " " + e["params"]["entry"].get("url", ""))
                report[v] = dict(chars=len(text or ""), console_errors=errs, expected=EXPECT.get(v), found=(EXPECT[v] in (text or "")) if v in EXPECT else None, head=(text or "")[:160].replace("\n", " | "))
                if a.shots:
                    shot = await c.send("Page.captureScreenshot", format="png")
                    Path(a.shots).mkdir(parents=True, exist_ok=True)
                    (Path(a.shots) / f"{v}.png").write_bytes(base64.b64decode(shot["data"]))
            print(json.dumps(report, indent=1))
            bad = {v: r for v, r in report.items() if r["console_errors"] or r["found"] is False or r["chars"] < 40}
            return 1 if bad else 0
    finally:
        proc.kill()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--shots")
    sys.exit(asyncio.run(main(ap.parse_args())))
