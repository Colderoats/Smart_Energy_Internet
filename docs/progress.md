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

# Module 2 — Digital Twin

## Stage 1 — Twin state layer (done)

**New, separate graph — does not touch Module 1's.** `app/twin/graph.py`
(the `twin` singleton backing `GET /nodes` / the Live Data tab) is
untouched, per this module's requirement that the Live Data tab stay
exactly as Module 1 left it. `app/twin/digital_twin.py` adds a second
NetworkX graph (`digital_twin` singleton) — same node set, but with the
alternate-path structure and routing state the self-healing layer needs.
Both graphs are fed from the same Module 1 pipeline: `app/ingestion/
pipeline.py`'s single choke point now calls `twin.update_node(...)`
(unchanged) and `digital_twin.update_node(...)` (new) on every normalized
reading, so this is additive to Module 1's ingestion, not a fork of it.

**Topology:** each of the 6 source nodes routes primarily through one of
two collector buses (`bus_a`, `bus_b`), which both feed `grid`. The other
bus is that node's one alternate route — `possible_connections` on each
node is a 2-option list (`architecture.md`'s "even if only 2-3 options"
bar). `rated_capacity_kw` per source (wind_01: 2000kW matching Module 1's
power-curve rating; hydro_01: 400kW, illustrative — no real plant behind
it; the 4 Kelmarsh nodes: 2050kW, the real Senvion MM92 rating) and
`capacity_kw` per bus (bus_a: 5000, bus_b: 6500 — sized just above each
bus's normal combined load) are demo figures for Stage 2's scoring
function to weigh, not a load-flow study — that's pandapower's job later.

**Mutation primitives live here, policy comes in Stage 2.** `reroute_node`,
`isolate_node`, `set_load_share` are on `DigitalTwin` (the state layer) so
Stage 2's decision engine has a clean API to call — but nothing calls them
yet; no auto-triggering exists until Stage 2. Each has a code-comment
human-override note: before any of these ever drive real actuation
hardware, a human-approval gate must sit in front of the call — this basic
pass applies automatically.

**New endpoint (backend-verification only, not the real frontend):** `GET
/twin/nodes` (`app/api/twin_routes.py`, its own router, prefix `/twin` —
kept separate from `app/api/routes.py` for the same reason the two
frontend tabs must stay separate). Returns the digital twin's nodes+edges.
The real Digital Twin tab UI is Stage 4.

**Verified:** imported `app.main` cleanly; ran the backend end-to-end
(after killing a stale backend process left running from an earlier
session on the same port — unrelated to this change) and confirmed `GET
/nodes` (Module 1, unchanged) and `GET /twin/nodes` (new) both serve real
live/replayed data concurrently. Sanity-checked the mutation primitives
directly: rerouting `wind_scada_kelmarsh_2` from `bus_b` to `bus_a` moved
its load correctly (`bus_a` 4450→6500kW, exactly at capacity; `bus_b`
6150→4100kW) and updated its edge; isolating `wind_scada_kelmarsh_3`
removed its edge and set `active_connection: null` / `isolated: true`;
`set_load_share` on `wind_scada_kelmarsh_4` set `load_share: 0.5`. Also
noted (not a bug): the real Kelmarsh 2016 data's winter-storm stop events
mean all 4 SCADA nodes already load as `health_status: "fault"` on a fresh
backend start — useful, since it means Stage 2's self-healing trigger will
have something real to react to immediately without needing a synthetic
fault injected.

## Stage 2 — Self-healing decision layer (done)

`app/twin/self_healing.py`. `maybe_trigger(node_id)` is called from
`app/ingestion/pipeline.py` right after every `digital_twin.update_node()`
call — same single choke point as everything else in the pipeline.

**Edge-triggered, not level-triggered.** It only acts when a node's
`health_status` *transitions into* `"fault"`/`"fault_predicted"` (tracked
via an in-memory `_last_health_status` dict), not on every subsequent
reading while it stays faulted. The Kelmarsh replay can hold a node in
`"fault"` for many ticks in a row (real consecutive "Stop" events) — without
edge-triggering, every one of those ticks would regenerate an identical
decision and spam the log. This wasn't asked for explicitly but followed
directly from "log the decision" implying each entry should represent a
distinct event, not a duplicate.

**Candidate generation** (`_generate_candidates`): 2-3 candidates per the
node's current state — one `reroute` candidate per unused entry in
`possible_connections` (normally 1, since each node has exactly 2), always
one `isolate` candidate, and one `reduce_load_share` candidate (fixed
50% curtailment — `CURTAIL_FRACTION`) unless the node is already isolated
(nothing to curtail with no active route).

**Scoring** (`_score`): returns `(unserved_kw, overload_kw)` per
candidate — architecture's two explicit criteria, combined via equal
weights (`WEIGHT_UNSERVED = WEIGHT_OVERLOAD = 1.0`, both in kW so directly
comparable) into one number to minimize. `isolate` always costs its full
contribution as unserved; `reroute`/`reduce_load_share` project the
resulting load onto the affected bus (`digital_twin.bus_load_kw`) and
compare to `BUS_CAPACITY_KW` to compute overload. Deliberately simple/
explainable, not a solver, per architecture's explicit scope.

**Auto-apply, no human gate.** `_apply` calls straight into
`DigitalTwin.reroute_node`/`isolate_node`/`set_load_share` — see those
methods' own human-override comments from Stage 1. Both the reconfigured
node and both buses' `current_load_kw` are re-broadcast as
`twin_node_update` WS messages right after applying, since the routing
change wouldn't otherwise reach the frontend until an unrelated update.

**Logging:** every decision records `trigger_health_status`,
`trigger_summary` (the real `fault_label` if the dataset's ground truth
fired, else a note that the statistical threshold fired), all candidates
considered with their scores, the chosen action, and a human-readable
`reason` string spelling out the full comparison — broadcast live as a
`twin_decision` WS message and persisted (Stage 3).

**Verified end-to-end:** on a fresh backend start, all 4 already-faulted
Kelmarsh nodes correctly triggered exactly one decision each, and every
logged score matched `bus_load_kw(via) + contribution` (reroute) or the
equivalent isolate/curtail formula traced through by hand against the
node's actual state at trigger time. Confirmed via direct `GET /twin/nodes`
that each node's `active_connection`/`isolated`/`load_share` matched its
logged decision.

## Stage 3 — Historical state + decision replay (done)

**New table, not a hypertable** (`app/db.py`): `twin_decisions` — one row
per self-healing decision (not per reading; volume is far lower than
`readings`), columns matching the decision dict Stage 2 builds, with
`candidates`/`chosen_params` stored as `JSONB` via `psycopg.types.json.Jsonb`.
`insert_decision()`/`fetch_decisions(node_id=None, limit=100)` mirror the
existing `insert_reading`/`fetch_history` pattern exactly, including the
same best-effort-on-read philosophy (callers catch and fall back to `[]`
rather than erroring the endpoint if the DB is briefly down).

**Deliberately did not add a separate "state snapshot" table.** Considered
logging every health_status transition separately from decisions, but each
self-healing decision already bundles both halves of "a fault happening AND
the twin's response" (its `trigger_summary`/`trigger_health_status` *is*
the fault moment, its `chosen_action`/`reason` *is* the response) — a
second table would just duplicate that pairing for no benefit. Kept it
simple, per this pass's "basic version" scope.

**New endpoints** (`app/api/twin_routes.py`):
- `GET /twin/nodes/{node_id}/history` — same underlying `readings` data as
  Module 1's `/nodes/{id}/history`, re-exposed under `/twin` so the Digital
  Twin tab's frontend code never calls into Module 1's API namespace.
- `GET /twin/decisions?node_id=&limit=` — the decision log, most recent
  first, optionally filtered to one node.

**Verified:** restarted the backend (picking up Stage 1's node data) and
confirmed decisions from *before* the restart were still returned by
`GET /twin/decisions` — durability across a process restart was the actual
point of persisting these rather than keeping them in memory.

## Stage 4 — Digital Twin tab frontend (done)

**New, fully separate frontend stack** — no shared state or view with
`LiveDataTab` (Module 1's view, extracted verbatim from the old `App.jsx`
into `frontend/src/tabs/LiveDataTab.jsx`, unchanged in substance):
- `hooks/useDigitalTwinSocket.js` — its own `WebSocket` connection to
  `/ws/updates` (same backend endpoint, but Module 1's `node_update`
  messages are explicitly ignored; only `twin_node_update`/`twin_decision`
  are consumed), plus initial `GET /twin/nodes` and `GET /twin/decisions`
  fetches.
- `components/DigitalTwinTopology.jsx` + `TwinNode.jsx` — a second React
  Flow graph with its own node renderer: sources on the left, `bus_a`/
  `bus_b` in the middle (this is where a reroute visibly swings an edge
  from one column to the other, and an isolate removes the edge
  entirely — since `digital_twin`'s NetworkX edges are the real, current
  routing state, not a fixed decoration), `grid` on the right. Bus nodes
  show a live load bar (`current_load_kw` vs `capacity_kw`) that turns red
  when overloaded; source nodes show `CURTAILED TO n%` / `ISOLATED` badges
  and which bus they're currently routed via.
- `components/DecisionLogPanel.jsx` — the live decision feed, newest first,
  each entry showing the trigger, the chosen action, and the full
  score-comparison reasoning string from Stage 2.
- `App.jsx` is now a thin tab shell (`Live Data` / `Digital Twin` buttons);
  only one tab is ever mounted at a time.
- `components/TimeSeriesPanel.jsx` gained one optional `historyUrl` prop
  (defaults to Module 1's endpoint if omitted) so the Digital Twin tab could
  reuse the existing Recharts widget against `/twin/nodes/{id}/history`
  instead of duplicating a whole chart component for a one-line URL
  difference — the only file shared between the two tabs, and it's a
  generic chart, not a "view."
- `vite.config.js` proxy gained a `/twin` entry alongside the existing
  `/nodes`/`/health`/`/ws`.

**Bug caught and fixed during verification:** `DigitalTwin.get_node()` was
edited (Stage 1 follow-up, for this stage's bus load bars) to add a derived
`current_load_kw` field for bus nodes, but the backend dev server still
running from Stage 2/3 testing didn't pick up the change (uvicorn
`reload=True` apparently didn't catch this edit). `TwinNode.jsx`'s
`BusNode` crashed on `undefined.toFixed()` as a result — caught via a
Playwright `pageerror` listener, root-caused by comparing the live
`GET /twin/nodes` response against the file on disk, fixed by restarting
the backend process (not a code bug). Lesson for next time: don't trust
`reload=True` on a long-running dev server across a session — restart
clean before a UI verification pass.

**Verified in an actual headless browser** (Playwright installed fresh
into the scratch dir again, `chromium-cli` still not available in this
environment): both tabs render correctly and distinctly — Live Data
unchanged from Stage 6, Digital Twin showing live bus overload
(`bus_a: 5475/5000 kW, OVERLOADED`), curtailed/rerouted source nodes with
their current routing, and a full, readable decision log with real
Kelmarsh fault labels and score breakdowns. Zero console errors after the
fix above. `GET /nodes` and `GET /twin/nodes` confirmed still serving
correctly side by side (Module 1 untouched).
