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

## Stage 5 — Rerouting-display bug fix + UI polish (done)

**The self-healing decision logic itself (backend) was never the
problem** — candidate generation, scoring (`min()` correctly picks the
lowest combined `unserved + overload`, no inverted comparison), applying
the chosen mutation, and the decision log all traced out correct on a
full walkthrough. The actual bug was in `useDigitalTwinSocket.js`: it
fetched `/twin/nodes`'s `edges` array once on mount and never updated it
from the WebSocket stream, while `DigitalTwinTopology.jsx` drew the graph
lines straight from that frozen array. So a live reroute/isolate updated
the node's own badges/text correctly (those come from `twin_node_update`
messages) but the line on the graph kept pointing at the node's original
bus forever — state reached the frontend, the graph just never redrew
it. Fixed by deriving edges live from each node's
`active_connection`/`isolated` fields on every update instead of a
one-time snapshot, plus a brief orange highlight flash on any edge whose
target just changed. Verified the edge now visibly follows real logged
reroutes (`wind_scada_kelmarsh_1` swinging `bus_a` <-> `bus_b` across two
screenshots, matching the backend's decision log) via a raw WebSocket
client and Playwright; couldn't catch the highlight's 2.5s flash itself
on camera since the Kelmarsh dataset's fault cluster is front-loaded and
stopped producing new reroutes partway through verification, but the
data flow it depends on is confirmed correct.

**UI polish, both requested by the user:** `EnergyNode.jsx` (Live Data
tab) gained a colored LIVE/REPLAYED badge and a per-node "Updated
HH:MM:SS" timestamp, both always visible on the node card, not a
tooltip. `DecisionLogPanel.jsx` (Digital Twin tab) turned out to already
render as a readable list, not raw JSON — no change was needed there.

# Module 3 — TA-GNN fault prediction

Model/experiment detail, measured results and the experiment log live in
`aiprogress.md`; this entry is the platform-side record (what was built, what
existing code was touched, deviations, bugs).

## Stage 1 — Offline pipeline, models, live inference, Digital Twin badges (done)

**Built:**
- `backend/ai/` (new; training, evaluation, artifacts — model files live only
  here; README-level docstring in `ai/__init__.py`): `taxonomy.py`,
  `features.py`, `dataset.py`, `models.py`, `training.py`, `metrics.py`,
  `evaluation.py`, `run_experiments.py`, `topology_eval.py`,
  `print_taxonomy.py`. One harness compares Baseline 0 (the Module 2 rule-based
  detector replayed offline with its label override OFF), Baseline 1 (plain
  GCN) and the TA-GNN (PyG `TAGConv`), plus a no-graph MLP ablation, on one
  chronological split with fixed seeds. `models.get_weights()/set_weights()` and
  `training.fit()/predict_logits()` are the seams Module 4's Flower wrapper
  will use (no Flower code written).
- `backend/app/ai_service/` (new): `predictor.py` (loads the saved artifact,
  windows replayed readings, scores on the twin's CURRENT edges),
  `integration.py` (rule-based verdict + TA-GNN verdict -> merged
  `health_status` + `flagged_by`).
- `backend/app/api/ai_routes.py` (new): `GET /ai/predictions`.
- Frontend, Digital Twin tab only: per-node detector rows (rule-based vs
  TA-GNN, probability, "Flagged: TA-GNN / rule-based" badges) in `TwinNode.jsx`
  plus a provenance sentence in `DigitalTwinTab.jsx`.

**Edits to existing Module 1/2 code (all additive, smallest possible):**
- `app/models/reading.py`: new optional `scada_channels: dict[str,float] | None`
  on `NormalizedReading` (approved: "widen the schema"). Distinct from the
  live-only `wind_speed`.
- `app/ingestion/scada_replay.py`: `SCADA_CHANNELS` map, `_resolve_scada_channels()`,
  and populating `scada_channels` per row. Existing fields/labels/ordering unchanged.
  Visible side effect: `latest_reading` in `GET /nodes` (Module 1) and `/twin/nodes`
  now carries an extra `scada_channels` key for SCADA nodes; the Live Data tab ignores it.
- `app/db.py`: `ALTER TABLE readings ADD COLUMN IF NOT EXISTS scada_channels JSONB`
  and one extra column in `insert_reading`. `fetch_history` untouched.
- `app/twin/digital_twin.py`: two default node attributes (`detectors`,
  `flagged_by`) and one method `set_detectors()`.
- `app/ingestion/pipeline.py`: one import and one call (`apply_detectors`) right
  after `digital_twin.update_node`, before the broadcast. Module 1's `twin`
  (Live Data tab) still receives the rule-based status only.
- `app/twin/self_healing.py`: `_trigger_summary` names TA-GNN when only TA-GNN
  raised the flag (otherwise it would misattribute to the statistical threshold).
  Per user decision, TA-GNN flags DO drive the existing edge-triggered self-healing.
- `app/main.py`: load the predictor in the lifespan (off the event loop) and include the AI router.
- `backend/requirements.txt`: `torch==2.14.0` (CPU wheel index), `torch_geometric==2.8.0.post1`.
  PyG core only, no torch-scatter/torch-sparse; no compilation. numpy/aiohttp etc. are their dependencies.

**Deviations / decisions worth knowing about:**
1. **Extra Kelmarsh years downloaded (2017, 2018), with approval.** With 2016 alone
   only 8 genuine fault events fell in the chronological test span. Files are in
   `backend/data/scada/extra_years/` (git-ignored by the existing rule; NOT read by
   Module 1's replay, whose glob is non-recursive). 2017-2018 are used for training/evaluation only.
2. **Training data comes from the CSVs, not TimescaleDB.** The `readings` table only holds
   whatever short demo replays ingested (days of Jan-Feb 2016, no temperature).
3. **Fault taxonomy (approved):** planned/routine/external stops are masked, not positives
   (basis: the status log's own IEC category + a short explicit message list).
4. **Docs vs data:** aiprogress.md §5.4 said labeled rows are spread across the whole year.
   That holds for any-Stop rows, but *genuine* fault starts are heavily winter-clustered
   (2016: 86 of 105 in Jan-Apr; 2017: 61 of 67 in Jan-Feb). Also the rich SCADA channels
   only exist from 2016-05-03 (all of 2017-2018 have them).
5. Stale doc references left as-is (not in scope): INSTRUCTIONS.md and several code comments
   cite `docs/architecture.md` / `docs/progress.md`; the files are at the repo root.

**Bugs found while building (all fixed):**
- NaN training loss from rows with no reading (NaN presence flags survived normalisation; a
  masked NaN is still NaN) — `Normalizer.apply`.
- Train/serve skew: scoring a turbine when its own reading arrived, while neighbours were a step
  behind, changed the model's input (a real flag at logit 2.87 was served below threshold).
  Fixed by scoring all turbines as one snapshot at a common reference step and refreshing all
  verdicts together; parity to 9.5e-7 (`ai/check_serving_parity.py`). Verdict `as_of` can trail a
  node's newest reading by a few dataset steps.
- Layout regression: the taller detector rows made the fixed-position Digital Twin nodes overlap;
  spacing increased in `DigitalTwinTopology.jsx`.

**Results:** the measured outcome is in `aiprogress.md` §4b. In short: on the held-out test split
no detector (rule-based or learned) raises a single true alarm, and the split has only 5 usable
independent fault events, so the comparison is inconclusive; on validation (optimistic for learned
models) the learned models beat the rule detector but TA-GNN ≈ GCN ≈ MLP.

**Not verified / open:** see aiprogress.md §8 (notably: no organic live TA-GNN flag was observed
in the running app) and §7 Q10–13 for decisions needed.

Also a stopped stale dev backend (`reload=True`, started before this session) was replaced by a
clean `python run.py`; the frontend dev server was left as it was.

# Module 4 — Adaptive federated learning

Model/experiment detail, measured results and the experiment log live in
`aiprogress.md`; this entry is the platform-side record.

## Stage 1 — Flower federation around the Module 3 TA-GNN (done)

**Built (all new, in `backend/ai/federated/`, README-level docstring in its `__init__.py`):**
- One Flower client PROCESS per Kelmarsh turbine plus a Flower server over localhost gRPC
  (`client.py`, `server.py`, `strategies.py`); strategies FedAvg (equal weights), FedProx (proximal
  term mu) and FedProx + adaptive weighting (`weighting.py`); local training with the proximal
  term (`local.py`); per-turbine shards (`partition.py`); SIMULATED dropout / degraded client /
  corrupted updates (`simulated.py`); the client/server boundary with an allow-list and per-run
  audit (`wire.py`); offline evaluation on the identical Module 3 test split (`evaluate.py`);
  grid runner, centralized reference, report, export, self-tests.
- Export of the final federated model in Module 3's artifact format
  (`ai/federated/artifacts/model_federated/`), loadable by the backend with plain torch.

**Edits to existing code (all additive, smallest possible):**
- `app/config.py`: new setting `ai_model_source` ("centralized" default | "federated"), env `AI_MODEL_SOURCE`.
- `app/ai_service/predictor.py`: `FEDERATED_ARTIFACT_DIR`; `load()` picks the artifact dir from the setting;
  `describe()` gains `source`.
- `app/ai_service/integration.py`: the `ta_gnn` verdict gains `model_source`.
- No frontend change: the Digital Twin tab tooltip already prints the verdict's model name, which now
  says "federated". Live Data tab untouched. No other Module 1/2/3 file touched.
- `ARCHITECTURE.md` / `INSTRUCTIONS.md` / `aiprogress.md`: federated layer, current focus, results.

**Deviations / decisions worth knowing about:**
1. **Separate virtualenv** (`backend/ai/federated/venv`, `requirements.txt`, approved): Flower 1.38 hard-pins
   fastapi 0.138 / uvicorn 0.49 / protobuf<7, conflicting with `backend/venv`; installing it there would have
   upgraded the Module 1-3 stack. Ray-based simulation is not installable on Windows + Python 3.14
   (`flwr[simulation]` pulls Ray only on non-Windows for >=3.13), so clients run as separate OS processes.
2. **Own-turbine client view** (approved): each client's graph has only its own turbine's features (a client
   cannot see neighbours' raw data); results are reported on both the full-snapshot view (Module 3 / serving)
   and the own-turbine view.
3. Uses Flower's legacy `flwr.compat` server/client API (the only simple local-process path in 1.38).
4. **The SIMULATED fault-tolerance comparison is mostly not run.** To finish quickly (on request) it was cut
   and then stopped: only seed-0 dropout for FedAvg and FedProx finished. The degraded-client and
   corrupted-update scenarios are implemented and self-tested but have no results. The clean grid
   (35 runs, seeds 0-4) is complete. Finish with `python -m ai.federated.run_all --stage scenarios`.
5. Centralized own-view reference: seed 0 only (Module 3's 5-seed numbers are the reused baseline).
6. Shards (~50 MB), the eval bundle (~22 MB) and run outputs in `ai/federated/artifacts/` are regenerable
   or bulky and are not git-ignored: your call.

**Bugs found while building (fixed):** wire audit wrongly demanded parameter arrays on metric-only
evaluation replies; the launcher waited on orphaned clients after a server crash; report writer used the
Windows default encoding for non-ASCII characters.

**Verified:** self-tests (adaptive rule maths, dropout schedule, wire allow-list rejections, prox term
shrinks the local update, bit-exact reproducibility); every federated run end to end (server + 4 client
processes + offline test evaluation); backend started cleanly on the default setting and with
`AI_MODEL_SOURCE=federated` (model card and every ta_gnn verdict state the source); `GET /nodes` (7 nodes /
6 edges), `GET /twin/nodes` (9 / 8), `GET /twin/decisions` unchanged.

**Not verified:** how adaptive weighting responds to dropout, a degraded client or corrupted updates (not run); the federated model producing an organic live flag; the Digital Twin tab in a browser with
the federated model (no frontend edit was made); TLS/DP/secure aggregation (not implemented).

# Module 5 — Blockchain ledger

## Stage 1 — EnergyLedger contract, ledger service, auto-recording, Blockchain tab (done)

**Built (all new unless noted):**
- `blockchain/` (Hardhat 2 project, repo root): `contracts/EnergyLedger.sol` (append-only: the only
  write function is `appendRecord`, owner-only; stores id, event type, keccak256 of the off-chain
  payload, actor/node id, block timestamp, recorder; emits `RecordAppended`), `test/EnergyLedger.test.js`,
  `scripts/deploy.js` (writes `deployments/<network>.json` with address + ABI), `hardhat.config.js`
  (localhost always; `sepolia` registered only when `SEPOLIA_RPC_URL` + `SEPOLIA_PRIVATE_KEY` are set).
- `backend/app/blockchain/`: `hashing.py` (canonical JSON + keccak256), `chain_client.py` (Web3.py, sync,
  always called from a thread), `store.py` (new `chain_records` table: full payload, hash, tx hash, block
  number/hash, gas, status, confirmations, verification, tamper-demo info), `events.py` (payload builders;
  provenance inside every hashed payload), `ledger.py` (queue worker, retry, confirmations, verify,
  integrity check, dev tamper, step timeline, twin hook).
- `backend/app/api/chain_routes.py`: `GET /chain/status`, `GET /chain/records` (paginated, `event_type`
  filter), `GET /chain/records/{id}` (record + 7-step journey), `POST /chain/verify/{id}`,
  `POST /chain/simulate-trade`, plus `POST /chain/replay-fl-rounds` (Module 4 ingest, idempotent) and
  `POST /chain/dev/tamper/{id}` (dev only). WebSocket: `chain_record` and `chain_status` messages on the
  existing `/ws/updates`.
- Frontend: `tabs/BlockchainTab.jsx` + `hooks/useBlockchainSocket.js` (same pattern as the Digital Twin
  hook: one initial fetch, then push only; no polling). Header (connection, network, contract, record
  count, integrity badge + "Re-check all"), type filters, live newest-first log (type badge, provenance
  badge, plain-English summary, status chip Pending/Sent/In a block/Confirmed, lock icon, short tx hash),
  detail view with the 7 numbered steps, "what this means" tooltips, Verify button, a clearly labelled
  dev-only tamper demo, and "Simulate P2P trade" / "Record federated rounds" buttons.

**What gets recorded:**
- `FAULT_ALERT` + `ENERGY_REDISTRIBUTION`: automatically, from the Module 2 self-healing layer, each time a
  node transitions into fault / fault_predicted (the same edge-triggered point that logs a twin decision).
  Includes which detector flagged it (rule_based / ta_gnn, probability, horizon), the chosen action,
  source/target node, kW affected, reason, and `twin_decision_id` = `<node_id>@<decision time>`
  (Module 2 decisions have no numeric id; this matches `GET /twin/decisions` rows).
- `P2P_TRADE`: only via `POST /chain/simulate-trade`; always `provenance: simulated`, settled in
  "demo credits". kWh defaults to 5-20 % of 15 min at the seller's latest reading, capped at rated capacity.
- `FL_ROUND`: via `POST /chain/replay-fl-rounds?run=<run>`; default run `fedprox_adaptive_mu1_clean_s3`
  (the exported federated model). Per-round, per-client weights and weighting factors come from that run's
  `round_log.json`; each round is cross-checked against `adaptive_weights_by_round.csv`
  (`csv_weights_match`, true for all 30 rounds). Labelled `offline_federated_run`.

**Edits to existing code (additive, smallest possible):**
- `app/twin/self_healing.py`: one import + one call (`ledger_hooks.on_self_healing(node, decision)`) after the
  decision is logged. It only schedules a task; it never awaits the chain.
- `app/main.py`: start/stop the ledger in the lifespan (started BEFORE ingestion so the first decisions are
  recorded) and include the chain router.
- `app/config.py`: `BLOCKCHAIN_*` / `SEPOLIA_*` settings. `app/db.py` untouched (the ledger creates its own table).
- `frontend/src/App.jsx`: third tab. `frontend/vite.config.js`: `/chain` proxy.
- `backend/requirements.txt`: `web3==8.0.0`. `.env.example`: blockchain variables. `.gitignore`: Hardhat
  `artifacts/`, `cache/` and `deployments/localhost.json`.

**How to run (local, default):**
1. `cd blockchain && npm install && npm run compile` (once; the backend's auto-deploy needs the compiled artifact).
2. `npm run node` (keep it running; local chain at http://127.0.0.1:8545, chain id 31337).
3. `npm run deploy:local` (optional: the backend auto-deploys if the node has no contract).
4. Start TimescaleDB and the backend as before (`python run.py`), then the frontend; open the Blockchain tab.
5. Tests: `cd blockchain && npm test`.

**Switching to Sepolia:** set `SEPOLIA_RPC_URL` and `SEPOLIA_PRIVATE_KEY` (an account funded with Sepolia
test ETH) in the repo-root `.env`, run `cd blockchain && npm run deploy:sepolia` (writes
`deployments/sepolia.json`), then set `BLOCKCHAIN_NETWORK=sepolia` and restart the backend. Records then
need 3 confirmations to lock (`BLOCKCHAIN_CONFIRMATIONS_SEPOLIA`), the tx step links to Etherscan, and the
tamper demo is off unless `BLOCKCHAIN_DEV_TOOLS=true`.

**Decisions / deviations worth knowing about:**
1. **Hardhat 2 (`hardhat@2.29`, toolbox 6) rather than Hardhat 3.** Same locked tool, mature CommonJS
   toolchain and `hardhat node`; chosen for reliability. No Ethers.js in the frontend: the backend is the
   only chain client and the UI reads everything through the API.
2. **Only the deployer can append** (owner check in the contract) so third parties cannot spam the ledger.
   The backend must hold that key. Locally that is Hardhat's publicly known account #0 key.
3. **Deployment identity = contract address + deployment block hash.** A restarted Hardhat node redeploys to
   the same address, so the address alone would make old records look tampered. Records from a previous
   local chain show "written to an earlier ledger contract" and Verify says "unavailable", not "mismatch".
4. **Step times are backend observation times.** Hardhat's own block timestamps ran about 40 s ahead of
   wall-clock when it mined many blocks per second, so the block's own time is shown separately.
5. The FAULT_ALERT is recorded at the same moment as the self-healing decision (on the transition into a
   fault state), not on every faulted reading, matching the decision log.

**Measured (local Hardhat node, 2026-09-28):**
- Hardhat tests: 10 passing (happy path, ABI has only `appendRecord`, existing records unchanged after
  further appends, owner-only, empty hash/actor/unknown type rejected, unknown id reverts, event
  emission with arguments, hash verification incl. a tampered payload, canonical JSON form).
- The Python and JavaScript canonical-JSON fingerprints of the same test object are identical.
- End to end with the running backend: real twin decisions from the Kelmarsh replay were recorded
  automatically (FAULT_ALERT then ENERGY_REDISTRIBUTION), plus simulated trades and the 30 FL rounds.
  Every record reached Confirmed. Created-to-confirmed time over 88 records: median 0.21 s; the maximum,
  62.8 s, was a record queued while the node was deliberately stopped.
- Gas per append: ENERGY_REDISTRIBUTION 142,543-145,343; FAULT_ALERT 165,243-165,255;
  P2P_TRADE 162,299-165,255; FL_ROUND 165,171-165,195.
- Verify returned "match" on untouched records. After the dev tamper it returned "mismatch", and the
  header integrity check listed exactly the tampered record ids.
- Outage test: with the node stopped, `/chain/status` reported `unreachable`, a new trade was stored as
  queued, and the API, twin and ingestion kept responding. After the node restarted, the backend
  auto-deployed, sent the queued record, and it confirmed and verified.
- Headless Chrome run of the Blockchain tab: the tab loads, a simulated trade shows steps 1-6 done, Verify
  shows match, tamper then Verify shows mismatch, the type filter works, no console errors.
- A second `replay-fl-rounds` call recorded 0 rounds and skipped 30.

**Known limitations / not verified:**
- **Sepolia is not exercised**: no RPC URL or funded key is available. The config, deploy script and
  backend switch were checked to load, but no transaction was sent to Sepolia.
- If TimescaleDB is down, new ledger events are logged and dropped (counted in
  `/chain/status.skipped_without_db`); only chain outages are queued for retry.
- Records from a reset local chain stay in the table and cannot be re-verified. FL rounds already recorded
  are not re-recorded on a new chain because replay is idempotent by run and round.
- The integrity check re-reads at most the 500 newest records of the current deployment on each
  `/chain/status` call and after each verify.
- The contract stores records in an unbounded array: fine for a demo and testnet, not tuned for gas at scale.
- No human-approval gate: redistributions are recorded as twin-only actions; nothing physical is switched.
- Found, not caused by Module 5 and not fixed: the backend's `reload=True` dev server hangs on reload
  (the old worker never finishes shutting down; reproduced with `BLOCKCHAIN_ENABLED=false`). Restart
  `python run.py` manually after code changes.
- Found, not fixed (Module 1 scope): the live hydro node's `power_output` read 57,988 kW against a 400 kW
  rated capacity. Simulated trades now cap at rated capacity; the reading itself is unchanged.

## Admin authentication (done, 2026-09-28)

**Built:**
- Access is invite-only for admins. Every dashboard view is behind login. `backend/app/auth/` holds the
  argon2id password policy, JWT and opaque tokens, the DB store and schema, the in-memory per-IP rate
  limiter, `require_admin`, WebSocket auth and the Origin-check middleware. `backend/app/api/auth_routes.py`
  has login, logout, refresh, me, register, and create/list invites.
- New tables: `users`, `invites`, `auth_audit_log`, and `refresh_tokens` (extra to the spec: rotated
  refresh tokens have to be stored server-side to be revocable). Created at startup like every other table.
- `backend/scripts/create_admin.py` bootstraps the first admin (prompts or `SEI_ADMIN_EMAIL`/`SEI_ADMIN_PASSWORD`).
  It refuses if an admin exists; `--force` creates another admin, or resets an existing one's password.
- Frontend: `/login`, `/register?token=`, and an "Invite admin" tab that shows the link once with a Copy
  button, plus an invite list. `AuthProvider` + route guard with return-to-previous-view, `apiFetch` (one
  silent refresh on 401, then to /login), `openAuthedSocket` (the WebSocket opens only after auth and
  refreshes + reconnects on close code 4401), and the admin email + Log out in the header. Client-side
  validation mirrors the backend password rules.
- `backend/tests/` has 36 pytest tests against a separate `sei_auth_test` database.

**Edits to existing code:**
- `app/main.py`: calls the auth schema init, fails fast without `JWT_SECRET`, adds a
  `RUN_BACKGROUND_TASKS=false` switch for tests, restricts CORS to `FRONTEND_ORIGIN` with credentials,
  adds the Origin-check middleware, puts `dependencies=[Depends(require_admin)]` on the
  nodes/twin/ai/chain routers, and turns API docs off by default.
- `app/api/routes.py`: `/ws/updates` moved to its own `ws_router` (router-level dependencies cannot
  apply to a WebSocket) and now authenticates on connect.
- `app/config.py`: auth settings. `requirements.txt`: `argon2-cffi`, `PyJWT`, `pytest`.
  `.env.example`: auth variables. The local `.env` got a generated `JWT_SECRET`, `COOKIE_SECURE=false`
  and `FRONTEND_ORIGIN` (the file is gitignored).
- Frontend: `App.jsx` (routing, guard, header), all `fetch(...)` calls in the hooks, `TimeSeriesPanel` and
  `BlockchainTab` switched to `apiFetch`, the three socket hooks switched to `openAuthedSocket`, and
  `vite.config.js` gained the `/auth` proxy plus `xfwd` for per-IP rate limiting.

**How to run:**
1. Make sure `JWT_SECRET` is set in the repo-root `.env` (see `.env.example`).
2. `cd backend && venv\Scripts\python -m pip install -r requirements.txt`
3. With TimescaleDB up, run `venv\Scripts\python scripts\create_admin.py` once.
4. Start the backend and frontend as before, open http://localhost:5173 and sign in.
5. Tests: `cd backend && venv\Scripts\python -m pytest tests -q`.

**Decisions / deviations:**
1. CSRF uses SameSite=Strict cookies plus an Origin/Referer check on every state-changing request.
   There is no CSRF token. The WebSocket also checks Origin (close code 4403).
2. No `react-router` dependency. A small history-API router is enough, and the stack rules say to
   ask before adding dependencies. Dashboard URLs are `/dashboard/<tab>` because `/twin`, `/chain` and
   `/nodes` are Vite proxy prefixes (a page reload on `/twin` would hit the backend).
3. Rejected WebSockets are accepted and then closed immediately, with 4401 or 4403, so the browser can see
   the code. Unauthenticated sockets are never added to the broadcast set. Authenticated sockets are
   closed with 4401 when the access token expires. The client then refreshes and reconnects, so an open
   socket never outlives its token.
4. Logout is public (it works with an expired access token) and revokes the whole refresh-token family.
5. A locked account returns the same generic "Invalid credentials". The login page explains the
   5-attempt / 15-minute lock in its error text instead of confirming that the account exists.
6. The users table carries `mfa_enabled` / `mfa_secret` for a later TOTP step; login already branches
   on `mfa_enabled`. 2FA itself is not built.
7. `/docs` and `/openapi.json` are off by default (they would otherwise be public). Set `API_DOCS_ENABLED=true`.

**Measured (2026-09-28):**
- `pytest tests`: 36 passed. Covered: login success (cookie flags, audit), generic failure for a wrong
  email and a wrong password, lockout after 5 failures and unlock after expiry, inactive user, login
  and register rate limits (429), foreign or missing Origin → 403, refresh rotation plus the grace
  window plus reuse revoking the family, expired refresh token, logout revocation, expired/forged/garbage
  JWT → 401, invite hashed and single-use, expired/used/invalid invite, weak/common/invalid registration
  input without consuming the invite, duplicate email 409, invite list without tokens, the exact
  protected-route list all 401 without a session, `/health` public, docs off, WebSocket 4401 without a
  session or with a bad cookie, 4403 for a foreign origin, a valid socket closing at token expiry, the
  password policy, and frontend/backend policy parity.
- Manual check against the running backend (both :8000 directly and through the :5173 Vite proxy) with
  no session: all 16 protected routes → 401, `/ws/updates` → close 4401, `/health` → 200. (Through :5173,
  `/ai/predictions` returns the SPA's index.html, because `/ai` has never been proxied. It is not backend
  data.) With a session, every GET → 200 and the socket delivered `node_update` frames. A foreign origin
  → 4403. After logout, `/nodes` → 401. Registering with an invite → 201, reusing it → 400, and the
  new admin could log in.
- `create_admin.py`: the first run created the admin, a second run refused (exit 1), and a common
  password was rejected even with `--force`.
- Headless Chrome: `/dashboard/twin` with no session redirected to `/login?next=%2Fdashboard%2Ftwin`. A
  wrong password showed the generic error. Login returned to `/dashboard/twin` (9 nodes rendered). The
  header showed the email. `document.cookie`, localStorage and sessionStorage were all empty. The invite
  page generated a link and listed invites. The Live tab badge showed "Live". Reload kept the session.
  Log out went to `/login`. `/register` without a token showed "Invite required". The client rejected
  `Password1234!` as too common. There were no console errors. With the access cookie replaced by an
  invalid value, the next requests got 401, one `/auth/refresh` ran (200), the requests retried with 200,
  and the WebSocket reconnected and received frames again. With the refresh cookie removed as well, the
  next action landed on `/login?next=%2Fdashboard%2Fchain`.
- The temporary verification accounts, invites and audit rows were deleted from `sei_db` afterwards, so
  the auth tables start empty and the first admin still has to be created with `create_admin.py`.

**Known limitations / not verified:**
- The rate limiter is in-memory and per process. Limits reset on restart and would multiply with
  several uvicorn workers.
- A revoked session's access token stays valid until it expires (at most 15 min) for REST and WebSocket
  calls, unless the user is deactivated (checked on every request). Logout clears the cookie in that browser.
- `COOKIE_SECURE=false` is set for local http. Production must serve HTTPS and keep the default `true`.
- Not exercised live: the 15-minute natural expiry of an open WebSocket in the browser. It is covered
  by the server-side test with a 2-second token, and by the browser test with an invalid token.
- There is no admin management UI yet (deactivate or remove admins, reset passwords). `create_admin.py --force`
  resets a password from the CLI.


# UI redesign — presentation layer (done, 2026-09-28)

Frontend-only. No backend, API, WebSocket payload, data model, auth, ML/FL or contract change. Every
existing feature still works; the views were restyled and regrouped.

**Built:**
- Design system in `frontend/src/ui/`: `theme.js` (colour = meaning: Solar amber, Wind teal, Hydro
  blue, Grid/Storage slate, blockchain violet, one indigo accent; green/amber/red only for status;
  friendly node names), `icons.jsx` (inline SVG icon set), `components.jsx` (Card, StatCard, Pill
  (Online/Offline/Training/Charging/Sold/Not sold/Pending), MockTag, Tabs, Segmented, Details
  expander, EmptyState, CopyButton, Button), `format.js`, `nav.js`, `AppShell.jsx` (dark navy
  sidebar in the fixed order Dashboard · Grid Map · Sources · Redistribution · AI Insights ·
  Analytics · Settings, admin avatar + name + log out at the bottom, top bar with page title,
  live indicator and avatar). Light content area, 14px+ body, 28-32px key numbers.
- Routes: `/dashboard/home|map|sources|chain|ai|analytics|settings`. Old URLs redirect:
  `live` -> `home`, `twin` -> `map?view=twin`, `invite` -> `settings?tab=admins`, so `?next=` links and
  bookmarks keep working. `safeNext` is unchanged.
- The top-bar live indicator shows the current page's own socket state: pages call
  `useReportConnection(connected)`. The shell opens no socket and does not poll.
- Screens:
  - **Login**: split screen. Left: title, tagline, inline-SVG hero (turbines, solar array, city at
    dusk, animated power line) and IoT / Digital Twin / AI / Blockchain chips. Right: Login form.
    "Register?" opens an inline invite box that accepts the full link or the raw token and hands off
    to the existing `/register?token=` flow. Registration stays invite-only.
  - **Dashboard**: 4 stat cards, one live "Energy flow" chart (wind / hydro / to grid; solar appears
    only when data exists), a live stream panel ("Attribute : Value" rows, newest first, about 8
    visible), and Live alerts. All derived client-side from `useDigitalTwinSocket` pushes.
  - **Grid Map**: tabs Topology | Federated Learning. Topology has a Live View / Digital Twin
    toggle. These are the existing `LiveDataTab` and `DigitalTwinTab`, still separate hooks and
    sockets, one mounted at a time. Nodes are compact icon cards (type icon, name, kW, status colour,
    Live/Replayed badge, updated time). The new `FlowEdge` sets line thickness from power carried and
    runs a dot in the direction of flow. The reroute highlight flash is kept. Clicking a node opens a
    side panel with its key values, detector verdicts (moved off the card), history chart and, in
    the twin, the decision log.
  - **Federated Learning** (new, `components/FederatedPanel.jsx`): a replay of the offline Module 4
    run. It shows a hub-and-spoke diagram with the Global Model (FedProx) in the centre and T1-T4
    around it. Each client's circle size is its adaptive weight, and its status ring cycles Training
    locally -> Uploading -> Aggregated. Dots animate updates going up to the hub and the global model
    coming back down. It also has a "Round N of 30" tracker with play/pause, a validation PR-AUC per
    round chart (FedAvg vs FedProx + adaptive), a train/validation loss chart, and a weights table
    with horizontal bars, local samples and last update/block. Weights come from the `FL_ROUND`
    ledger records when they exist, otherwise from the same run's snapshot.
  - **Sources**: cards grouped Turbines / Hydro / Solar with a type filter. Each card shows a status
    pill, current output, efficiency (output / rated capacity) and a sparkline (existing
    `/twin/nodes/{id}/history` plus pushes). Click to expand the details. Solar shows an empty state
    because there is no hardware yet.
  - **Redistribution (Blockchain)**: flow cards (seller/surplus green -> kWh + ₹ -> buyer/deficit
    red for trades; faulted node -> new bus for self-healing), each with a "Recorded / Verified on
    chain · block" badge. A horizontal strip of recent blocks (click one to list its records). A
    transactions table (Buyer, Seller, Qty, Amount ₹, Sold / Not sold / Pending, short tx hash + copy).
    A new "Topology changes on chain" timeline built from twin decisions (reroute / isolate / curtail)
    joined to the block of their `ENERGY_REDISTRIBUTION` record via `payload.twin_decision_id`, with
    the reason behind "Why". The full existing ledger explorer (filters, 7-step journey, Verify,
    dev tamper demo, Simulate P2P trade, Record federated rounds) is below, restyled. Clicking a
    card, block or trade opens that record in it.
  - **AI Insights**: fault-risk card (Low/Medium/High plus the reason and the highest TA-GNN score,
    labelled "TA-GNN · centralized|federated"), a fault-detection card, a 24h demand forecast with
    the peak marked, and up to 3 rule-based recommendation cards with one action button each. Detail
    sits behind "Details".
  - **Analytics** (new, before Settings): 4 stat cards (Money saved ₹, Energy redistributed kWh, CO₂
    avoided, Grid dependency reduced), a cost chart (with SEI vs grid only; Daily / Weekly / Monthly),
    a generation-mix donut, a self-healing card, a baseline-vs-SEI bar (FedAvg vs FedProx + adaptive)
    and a 7 / 30 day range selector.
  - **Settings**: profile card (avatar, name, role, email, member since, Edit Profile) plus tabs
    Profile, Security, Notifications, System (backend, DB, ledger, AI model status, fetched once) and
    Admins (the existing Invite admin page, unchanged).

**Mocks** (all in `frontend/src/mocks/uiMocks.js`; the UI shows a "Mock data" tag wherever a MOCK
value is displayed):
- MOCK `mockConsumptionKw` / `MOCK_CONSUMPTION_RATIO` (0.82 x generation). There is no consumption metering.
- MOCK `mockDemandForecast24h`. No demand-forecast model exists; TA-GNN forecasts faults only.
- MOCK `MOCK_TARIFFS`, `MOCK_CO2_TONNES_PER_MWH`, `mockCostSeries`, `MOCK_GRID_DEPENDENCY`: Money
  saved, CO₂ avoided, Grid dependency and the cost chart. No billing or emissions data exists.
- MOCK `MOCK_DOWNTIME_MIN_PER_HEAL` (18 min per self-healing action): "Est. downtime avoided".
- MOCK `MOCK_NOTIFICATION_PREFS`: Settings -> Notifications toggles (local state, not saved).
- SNAPSHOT (real measured numbers, copied statically) `FL_RUN_SNAPSHOT`: per-round validation
  PR-AUC for `fedavg_clean_s3` and `fedprox_adaptive_mu1_clean_s3`, train loss, normalised validation
  loss and adaptive weights, from each run's `round_log.json`. Used for the comparison and loss
  charts, and as the weights fallback when no FL_ROUND records are on the ledger.
- SNAPSHOT `FL_CLIENTS`: training samples per client, from `partition_report.json`.
- SNAPSHOT `FL_BASELINE_COMPARISON`: validation PR-AUC, test ROC-AUC and localisation top-1 (5-seed
  means, clean scenario), from `RESULTS.md`.

**Real data used (no mock):** generation, stability, active nodes, energy-flow chart, stream, alerts,
sources, generation mix, TA-GNN risk and detection (twin nodes); self-healing counts and the topology
timeline (`/twin/decisions`); flow cards, blocks, trades, "Energy redistributed" kWh and FL weights
(`/chain/records`); model card and system status (`/ai/predictions`, `/health`, `/chain/status`).

**Edits to existing code (presentation only):**
- `App.jsx`: new shell, routes and legacy redirects. Auth guard logic unchanged.
- `BlockchainTab.jsx`: dark classes mapped to light ones, plus an optional controlled
  `selected`/`onSelect` prop. Logic, API calls and features unchanged.
- `LiveDataTab.jsx`, `DigitalTwinTab.jsx`: new layout and side panel; same hooks and components.
- `EnergyNode.jsx`, `TwinNode.jsx`: compact icon cards. `DetectorRows` is now exported and shown in the
  side panel. `TopologyView.jsx`, `DigitalTwinTopology.jsx`: `FlowEdge`, a tighter layout and a light
  canvas. Edge derivation and the reroute highlight are unchanged.
- `TimeSeriesPanel.jsx`: light colours and an optional `color` prop. Data logic unchanged.
- `DecisionLogPanel.jsx`, `InviteAdminPage.jsx`, `RegisterPage.jsx`, `AuthForm.jsx`, `LoginPage.jsx`,
  `index.css`: restyled. The login/register validation and flows are unchanged.
- `vite.config.js`: added the `/ai` proxy. `GET /ai/predictions` was never proxied (noted in the auth
  section above) and AI Insights / Settings need its model card.
- No new dependency. lucide-react is not installed, so an inline SVG icon set is used instead
  (INSTRUCTIONS.md: ask before adding dependencies). Recharts was already present.

**Decisions / deviations:**
1. The two briefs conflicted on colours and the tagline. I used the later brief: Wind teal, Hydro blue,
   Grid slate. Blockchain is violet and the accent is indigo. Tagline: "Path to a sustainable future".
2. Accuracy is not charted for FL. At about 0.1% positives, a model that never predicts a fault
   scores 99.9%. The charts use validation PR-AUC and loss, and the "About this metric" note says
   test-set PR-AUC is near chance (RESULTS.md).
3. P2P amounts are demo credits shown with a ₹ sign as the brief asked. Every trade is tagged
   "Simulated", and the table footnote says no real money moved.
4. FL training is offline. The FL tab is a labelled replay, not live training.
5. The Topology timeline shows only event types the twin actually produces (reroute, isolate =
   "node removed from grid", curtail). Node-added events do not exist (fixed topology), so none are
   invented.
6. Redistribution opens 3 sockets (unfiltered overview, trades, explorer) plus the twin socket for
   decisions. They are separate uses of the existing hooks; the hooks were not changed.
7. Node cards keep the always-visible Live/Replayed badge and "Updated" time (an earlier user
   request and the data-sourcing rule). Detector rows moved to the side panel.

**Verified (2026-09-28, headless Chrome through the Vite proxy, backend + TimescaleDB + Hardhat running):**
- `npm run build` and `npm run lint` (oxlint): clean, 0 warnings.
- `/dashboard/twin` without a session -> `/login?next=...`. The inline Register? box rejects a bad
  invite. After login the user lands on `/dashboard/map?view=twin`, and `/dashboard/invite` lands on
  Settings -> Admins.
- Every screen rendered with live data and the top-bar indicator showed "Live": all 6 sources, bus
  loads, decisions, 211 ledger records (8 trades in the table, 30 FL rounds read from the ledger,
  "From ledger"), the TA-GNN model card ("centralized") and system status all Online.
- Clicking a trade opened its record journey with Verify in the explorer.
- No page errors. The only console errors were the expected 401s from the pre-login `/auth/me`
  session check.
- A temporary admin was created for the check with `create_admin.py --force` and deleted afterwards
  (user, audit rows, refresh tokens). Only the original admin remains.

**Failures hit during the work (fixed):**
- The first build failed: a scripted import insert matched every `import {` line in
  `TimeSeriesPanel.jsx` (duplicate declarations). Fixed.
- The trades table was empty because the unfiltered newest-50 page held only fault and FL records.
  Fixed with a dedicated `P2P_TRADE` hook.
- The block strip mixed block numbers from a previous local-chain deployment (#94 above the current
  chain's #21). It now shows only `deployment_current` records.
- The map legend overlapped React Flow's zoom controls. Moved to the top-right.
- AI Insights showed "High" next to a 0.5% top score without saying why. It now states the reason
  (for example "2 nodes are already in a fault state").

**Known limitations / not verified:**
- The FL diagram replays the recorded run. It does not reflect a training job in progress.
- Mocked values (list above) are placeholders to be wired to real sources later.
- The live hydro reading (57,988 kW vs 400 kW rated, the Module 1 issue above) dominates the
  energy-flow chart scale, edge widths and the donut. The UI shows it as-is.
- Not checked: narrow and mobile widths (the layout targets desktop, with a fixed 240px sidebar), and
  the animations with `prefers-reduced-motion` beyond the CSS rule.
- Edit Profile is disabled: there is no profile-update endpoint.
