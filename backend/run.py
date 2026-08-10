"""
Dev entrypoint. On Windows, the event loop policy must be forced to the
selector implementation *before* uvicorn creates its event loop — psycopg3's
async pool cannot run on ProactorEventLoop, and setting the policy inside
app/main.py runs too late (uvicorn's `python -m uvicorn ...` CLI creates the
loop before importing the app module). Run the backend with `python run.py`
instead of `uvicorn app.main:app` directly.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
