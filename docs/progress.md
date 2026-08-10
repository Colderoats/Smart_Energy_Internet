# Progress Log

Short entries per stage: what was built, key decisions, deviations. Read this
before re-scanning the codebase.

## Stage 1 — Project skeleton (done)

**Built:**
- `backend/` — FastAPI app skeleton, no ingestion/business logic yet.
  - `app/config.py` — pydantic-settings, reads `.env` at repo root.
  - `app/db.py` — TimescaleDB connection pool (async), `connect()` /
    `disconnect()` / `ping()`. Startup failure is caught and logged, not
    fatal — `/health` reports `db: "disconnected"` instead of crashing the
    app, since Postgres/Timescale won't always be up in dev.
  - `app/main.py` — app instance, lifespan-managed DB pool, `GET /health`.
  - `run.py` — dev entrypoint. **Use this instead of
    `uvicorn app.main:app` directly** (see deviation below).
  - `app/models/`, `app/ingestion/`, `app/twin/`, `app/api/` — empty
    placeholder packages for stages 2–5.
- `frontend/` — Vite + React 19 + Tailwind v4 skeleton.
  - `App.jsx` fetches `/health` on load and displays the raw JSON — just
    proves the frontend can reach the backend. No topology/chart UI yet
    (that's Stage 6).
  - `vite.config.js` proxies `/nodes`, `/health`, `/ws` to
    `localhost:8000`, matching the API spec in architecture.md exactly (no
    `/api` prefix).
- `docker-compose.yml` (repo root) — single `timescaledb` service
  (`timescale/timescaledb:latest-pg16`), reads credentials from `.env`.
- `.env` / `.env.example` — DB credentials for docker-compose + backend.

**Verified:** backend starts, `/health` returns
`{"status":"ok","db":"disconnected"}` when Timescale isn't running, and
`{"status":"ok","db":"connected"}` once it is — confirmed end-to-end against
the actual `sei_timescaledb` container. Frontend dev server loads and its
proxy correctly forwards `/health` to the backend.

**Port collision on this machine — resolved:** host port 5432 is already
used by an unrelated Docker container (`food_redistribution_db`), and port
5433 is separately taken by a native Windows PostgreSQL 18 service. Both
collisions produced the *same* misleading symptom (`password authentication
failed for user "sei_user"`) because the connection was silently being
answered by the wrong Postgres instance, not by our container. Settled on
host port **5434** for `sei_timescaledb`, reflected in `docker-compose.yml`
and `.env`/`.env.example`. If TimescaleDB connections ever fail with a
password error again on this machine, check `netstat -ano | grep 5434`
first for a similar squatter before assuming the credentials are wrong.

**Deviations / decisions worth knowing about:**

1. **asyncpg → psycopg3.** requirements.txt originally used `asyncpg`
   (the common async Postgres driver), but it has no prebuilt wheel for
   Python 3.14 yet and this machine has no MSVC Build Tools to compile it
   from source. Switched to `psycopg[binary,pool]` (psycopg3), which ships
   binary wheels for 3.14 and has equivalent native async support. Not a
   deviation from the locked stack (CLAUDE.md only specifies "TimescaleDB"
   storage, not a driver) — just flagging the substitution and the reason.
2. **Windows + psycopg3 async needs a custom entrypoint.** psycopg3's async
   pool can't run on Windows' default `ProactorEventLoop`; it needs the
   selector event loop. That has to be set *before* uvicorn creates its
   loop, which is too late if you run `uvicorn app.main:app` from the CLI
   (it builds the loop before importing the app module). `backend/run.py`
   sets the policy first, then calls `uvicorn.run()` — always start the
   backend with `python run.py`, not the bare `uvicorn` CLI, on Windows.
3. **Frontend is plain JS, not TypeScript.** CLAUDE.md doesn't specify a
   language for the frontend beyond "React + React Flow + Tailwind +
   WebSockets." Defaulted to JS to keep the skeleton minimal — flag if you
   want TypeScript instead, it's a bigger change to make later than now.
4. **Tailwind v4** (`@tailwindcss/vite` plugin) used instead of the v3
   `tailwind.config.js` + PostCSS setup — v4 is the current default via
   `npm create vite` tooling and needs no config file for this project's
   needs.

**Port note (later addendum):** host port 5434 also later collided in the
same way once more services were tested — see the Stage 2 entry below for
the final resolution.

## Stage 2 — Live wind/hydro ingestion (done)

**Source chosen:** [Open-Meteo](https://open-meteo.com) — free, no API key.
Forecast API (`api.open-meteo.com/v1/forecast`) for real current wind speed
at `wind_01`'s coordinates; Flood/GloFAS API (`flood-api.open-meteo.com`)
for real daily river discharge at `hydro_01`'s coordinates. Considered EIA
(US-only, needs a signup key, no wind_speed field at all — still would've
needed Open-Meteo alongside it) — Open-Meteo covers both fields from one
key-free provider. User confirmed this choice.

**Neither endpoint reports electrical power output** — `power_output` is
therefore *estimated* from the real live reading via textbook physics
formulas, not metered: a generic cubic wind-turbine power curve
(cut-in 3 m/s, rated 12 m/s, cutoff 25 m/s, 2000 kW rated) for wind, and
`P = ρ·g·Q·H·η` (assumed 30 m head, 0.85 efficiency) for hydro. Both are
illustrative demo parameters, not any real plant's spec — commented as such
in `app/ingestion/live_source.py`. This is live API-sourced data, not
physically sensed — see CLAUDE.md's data-sourcing rules.

**Demo coordinates** (configurable via `.env` — `WIND_NODE_LAT/LON`,
`HYDRO_NODE_LAT/LON`): wind at Muppandal, Tamil Nadu (one of India's
largest onshore wind-farm clusters); hydro at Mettur Dam on the Kaveri.
Both placeholders, not tied to any specific real turbine/plant.

**Interpolation — flagged, not built.** architecture.md raised smoothing
the frontend by interpolating between real API points if the real cadence
(hourly/daily) is too coarse to visibly animate, and said to flag this
rather than just doing it. Decision: skipped it for now — the live poller
polls Open-Meteo directly every 60s (`live_poll_interval_seconds`) and
pushes whatever it gets. Consecutive polls will often repeat the same
number until the source's own hourly/daily value changes; that's expected,
not a bug. Revisit if the demo needs snappier visible motion on the live
nodes — would need a WS-only interpolated tick path that never touches the
DB (ground truth should stay real-values-only).

**Files:** `app/ingestion/live_source.py` (fetch + power-curve math),
`app/ingestion/poller.py` (background loop, started from `main.py`
lifespan), `app/models/reading.py` (the `NormalizedReading` pydantic model
every source conforms to).

**Verified:** live end-to-end — polled Open-Meteo, got real wind
speed/discharge, wrote rows into `readings`, confirmed via
`docker exec sei_timescaledb psql ...`.

**Second port collision, resolved:** host port 5433 (the first fallback
from Stage 1) turned out to *also* be taken, by a native Windows PostgreSQL
18 service — same misleading "password authentication failed" symptom as
the original 5432 collision, for the same reason (wrong Postgres instance
silently answering the connection). Moved to host port **5434**, confirmed
free by `netstat`, and this one held. `docker-compose.yml` and
`.env`/`.env.example` reflect 5434.

## Stage 3 — SCADA replay (done — dataset pivoted from EDP to Kelmarsh)

**Original plan was the EDP wind-turbine dataset** (per CLAUDE.md's
"EDP-style" hint) — couldn't script its download (Kaggle needs an
authenticated session, EDP's own portal 403s automated requests). User
supplied a Kaggle API token, which unblocked scripted downloads generally,
but **the only real Kaggle mirror findable for the EDP dataset turned out
to be a 11.7 GB anonymized multi-farm reupload** (numbered sensor columns,
no named fields) — not the compact, well-documented ~219MB EDP set this
was designed against, and far too large to be practical here anyway.
Stopped that download after confirming its size/shape from the listing
rather than pulling all 11.7 GB to find out.

**Switched to the [Kelmarsh wind farm dataset](https://zenodo.org/records/8252025)**
instead — real operational data from 6 Senvion MM92 turbines in
Northamptonshire, UK, released by Cubico Sustainable Investments under
CC BY 4.0, hosted directly on Zenodo with **no login required** (unlike
Kaggle/EDP). Downloaded just the 2016 year (~98MB zipped) via plain
`curl`, extracted turbines 1–4 (of the farm's 6) into
`backend/data/scada/`. This is not a downgrade from the original plan —
if anything it's a better fit: real named SCADA columns (not anonymized),
and a genuine per-turbine event/status log with real start/end timestamps
and human-readable fault messages (e.g. "Emergency stop nacelle"), which
is more precise than EDP's point-in-time failure logbook would have been.

**File format quirk handled:** both file types (`Turbine_Data_Kelmarsh_*`,
`Status_Kelmarsh_*`) have several `#`-prefixed metadata comment lines
before the real header row (which is itself `#`-prefixed in the
Turbine_Data files, not in the Status files) — `_read_kelmarsh_csv()` in
`app/ingestion/scada_replay.py` locates the true header row and hands a
normal `csv.DictReader` back from that point on. Missing/erroneous values
are the literal string `"NaN"` in the source; parsed to `None`, not
coerced into a number (`_parse_float()`).

**Columns resolved by pattern-matching** (priority substrings like
`"generator bearing rear temperature"`, `"power (kw)"`, with fuzzy
fallbacks), same defensive approach as originally planned, and **verified
directly against the real downloaded headers** this time — confirmed via
a throwaway script (not committed) that real values flow through
correctly, e.g. `power=353.8 kW, temperature=41.5°C` for turbine 1 in
May 2016. Turbine identity comes from the filename
(`Turbine_Data_Kelmarsh_<n>_...csv`), not an in-file column — Kelmarsh
ships one file per turbine, unlike EDP's single multi-turbine file the
original design assumed.

**No true vibration channel** in this (or any other wind-turbine
SCADA+fault dataset found) as a clean scalar — user confirmed: leave
`vibration: null` throughout rather than fabricate a proxy value (see
Stage 4). `type` is always `"wind"` — Kelmarsh has no hydro turbines.

**Fault labeling:** only `Status == "Stop"` events from the real log are
treated as `fault_label` ground truth, using the event's own real
start/end window (not a lookback heuristic — Kelmarsh's log gives an
actual duration, unlike EDP's point-in-time failure log this was
originally designed around). `"Warning"`/`"Informational"` events are
skipped — they fire constantly during normal operation and would
otherwise mark almost the whole dataset "fault", drowning out Stage 4's
rolling-baseline detector. Turbine 1 alone has 129 real "Stop" events in
just 2016.

**Replay ordering — round-robins across all 4 turbines** (one row from
each in turn) rather than exhausting turbine 1's ~52k rows (which at the
2s replay interval would take ~29 hours) before turbine 2 shows any
activity — keeps every twin node visibly live within the same short demo
window. Loops back to the start on reaching the end of the data — a demo
mechanism, not a claim about real elapsed time.

**Verified fully end-to-end** against the real, downloaded data — not a
synthetic fixture this time: restarted the backend, confirmed all 4
`wind_scada_kelmarsh_*` twin nodes updating within seconds via
`GET /nodes`, and confirmed in the actual browser (Playwright screenshot)
that a real "Emergency stop nacelle" event correctly renders all 4 nodes
red/"FAULT" (their 2016 data happens to open with a dense run of real
winter-storm stop events across the farm).

**Only 2016 is loaded.** `backend/data/scada/` will pick up additional
years automatically (`_iter_turbine_readings` globs
`Turbine_Data_Kelmarsh_<n>_*.csv` per turbine) if more of Zenodo record
8252025's yearly zips (2017–2022) are ever added — no code change needed,
just download + extract more files into that directory.

**Kaggle token:** stored at `~/.kaggle/kaggle.json` (the standard location,
outside the repo — never commit this file). `kaggle` was pip-installed
into `backend/venv` as a one-time download tool; it's not added to
`requirements.txt` since the running app doesn't depend on it.

## Stage 4 — Fault detection (done)

`app/twin/fault_detection.py`. Historical readings only (live wind/hydro
nodes have no fault-relevant fields in this phase — always "normal", per
architecture.md's scope). Per-node rolling window (last 50 temperature
readings) computes a live mean/std baseline; a reading ≥3σ above baseline
is "warning", ≥5σ is "fault_predicted". A non-null `fault_label` from the
dataset's real event log always overrides to "fault" — ground truth wins
over the statistical guess. Verified twice: against a throwaway synthetic
fixture before the real dataset was in place, and again end-to-end against
the real Kelmarsh data once downloaded (Stage 3) — a real "Emergency stop
nacelle" event correctly drove a node to "fault" and rendered red in the
browser.

## Stage 5 — API + WebSocket (done)

`app/api/routes.py` + `app/api/ws_manager.py`, exactly per
architecture.md's spec: `GET /nodes` (full twin state + edges), `GET
/nodes/{id}/history` (from TimescaleDB, best-effort — returns `[]` rather
than erroring if the DB is briefly unreachable), `WS /ws/updates` (push
only; a `ConnectionManager` broadcasts every ingested reading, from either
source, to all connected clients as `{"type": "node_update", "node": ...}`).
`app/ingestion/pipeline.py` is the single choke point both the live poller
and the SCADA replay push through — normalize → fault-detect → update twin
→ persist → broadcast — so live and historical data are never handled
differently by anything downstream. Verified: connected a raw WebSocket
client, received a real `node_update` push from the live poller's next
cycle.

## Stage 6 — React frontend (done)

Vite + React + `@xyflow/react` (React Flow) + Recharts + Tailwind v4.
- `hooks/useTwinSocket.js` — fetches `/nodes` once on mount, then a
  `WS /ws/updates` connection keeps every node's state current; also
  surfaces a `connected` flag for the header's Live/Disconnected badge.
- `components/TopologyView.jsx` + `EnergyNode.jsx` — React Flow graph,
  fixed hand-placed layout (topology is static this phase), node color
  keyed off `health_status` (green/amber/orange/red for
  normal/warning/fault_predicted/fault), click a node to select it.
- `components/TimeSeriesPanel.jsx` — Recharts line chart of the selected
  node's `power_output`; loads history from `GET /nodes/{id}/history` on
  selection, then live-appends each WS push for that node.
- Header legend explicitly calls out that `wind_scada_*` node IDs are
  replayed historical data, not live — the "clear visual distinction
  between live and historical" architecture.md asked for.

**Verified in an actual headless browser** (Playwright — `chromium-cli`
wasn't available in this environment, so installed Playwright + Chromium
directly into the scratch dir, not the project, for a one-off check): page
loads, title correct, all 7 nodes render and connect to `grid`, WS badge
shows "Live", zero console errors, real live power-output data plotted.
One bug caught and fixed this way: React Flow node handles were on the
wrong sides (`source`/`target` swapped), making edges swoop off-canvas
before reaching `grid` — fixed in `EnergyNode.jsx`, re-verified clean.
