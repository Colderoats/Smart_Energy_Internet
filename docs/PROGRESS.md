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

## Stage 2 — More data, new split, retrained model (2026-09-29)

Pointer entry; details in aiprogress.md EXP-013 to EXP-015 and §4b.
- **Data:** Kelmarsh SCADA 2019–2022 (Zenodo 8252025, turbines 1–4) added to
  `backend/data/scada/extra_years/` (training/eval only; Module 1's replay does not read it).
- **Code:** `ai/dataset.py` now has named splits (`SPLITS`, `ACTIVE_SPLIT = "exp013"`: train 2016–2019,
  val 2020, test 2021–2022) with an explicit `test_end`. `ai/run_experiments.py` gained `--split`, and
  writes one results file per kind subset. No serving code changed.
- **Deployed model replaced:** `ai/artifacts/tag/` is now the `exp013` TA-GNN (it beat the rule
  baseline on the new test split, as the pre-registered rule required). Previous artifact backed up to
  `ai/artifacts/tag_exp002/`. Serving parity re-checked (max logit difference 4.8e-7).
- **Follow-up (same day):** wind-regime features (EXP-015) were run: no gain, so not deployed. Module 4 was
  partly re-run on the new split (EXP-016, 5 of 9 runs; old federated artifacts moved to
  `ai/federated/artifacts/exp002/`; `model_federated/` unchanged). A held-out serving-path check
  (EXP-017) shows the deployed model flagging real 2021–2022 faults 10–53 min ahead. New code:
  `ai/features.RegimeResiduals`, `ai/dataset.fit_regime`, `run_experiments --regime` (training/eval only).

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


---

## Testbed + paper reproduction (started 2026-10-12) - LIVE STATUS, updated as the work proceeds

Goal: make the implementation do what the conference and journal papers describe and reproduce their experiments from real runs on a **simulated testbed**
(`provenance: "simulated_testbed"`, never mixed with the real Kelmarsh results). Rules followed: additive only, no git, locked stack, no households, every new route admin-protected,
settings pre-registered in `backend/testbed/PREREGISTRATION.md` before measured runs, paper numbers only shown as "Paper target" (`experiments/paper_targets.json`, 217 entries).

### Decisions taken (the user delegated them: "do whatever you recommend")
- pandapower / torch / PyG live in a separate venv `backend/testbed/venv` (Python 3.14.6; torch 2.14.0+cpu, torch_geometric 2.8.0.post1, pandapower 3.5.6, scikit-learn 1.9.1, web3 8.0.0). `backend/venv` is untouched (pandapower would have upgraded its networkx/numpy pins).
- No onnx / python-docx (papers parsed with the standard library). Topology B = IEEE-14 branch graph rebuilt as an 11 kV microgrid. Papers were read from `C:\Users\deepa\subcode\`.
- Solidity 0.8.24 (the repo's Hardhat config) for the new contract; the papers say 0.8.20 (journal) and 0.8.24 (conference).

### Done (code written; tests pass)
- `backend/testbed/`: topologies A (6 nodes / 5 lines), B (14 / 20), C (IEEE 33-bus + 5 ties = 37 lines, paper line numbering kept), power flow incl. islanded sections, journal simulator (24 h @ 5 s = 17,280 samples, 4 fault types x 5), conference 12-node ring testbed (365 d @ 15 min = 420,480 samples), journal twin evaluation (Omega, J = w1 E_uns + w2 V_viol + w3 N_sw, default scheme vs twin, T_rec, E_uns), conference twin (Eqs. 1-6), topology-aware redistribution with pandapower feasibility and web3 settlement.
- `backend/ai/testbed_models/`: joint TA-GNN (Eqs. 11-14, torch-only core), GCN baseline, conference forecasting models (TA-GNN, TA-GNN without adaptation, LSTM, GRU, GCN, TGNN), journal FL loop.
- `backend/ai/federated/`: `weighting_paper.py` (journal Eq. 16 and conference Eqs. 11-12), `strategies_testbed.py` / `client_testbed.py` / `server_testbed.py` / `run_testbed.py` (Flower path); `wire.py` allow-list gained `n_k`, `v_k`. Existing strategies, runs and rule untouched.
- `blockchain/contracts/EnergyMarket.sol` + `test/EnergyMarket.test.js` (12 passing) + `scripts/deploy_market.js`. EnergyLedger untouched.
- `backend/app/api/testbed_routes.py` (prefix `/testbed`, 10 read-only GET routes, included with `dependencies=protected`); `tests/test_auth.py` pinned list extended; `tests/test_testbed_routes.py` added (needs TimescaleDB, not yet run).
- Frontend: `ResultsTab`, `TopologiesTab`, `GraphsTab` (+ `src/testbed/`), three nav entries after Analytics, `/testbed` proxy prefix. `npm run build` and `npm run lint` clean.
- `experiments/`: `build_targets.py`, `run_all.py`, `train_farm.py`, `fl_runner.py`, `job_twin.py`, `job_trading.py`, `contract_bench.py`, `journal_tables.py`, `conf_tables.py`, `trading_tables.py`, `export_all.py`, `export_topologies.py`, `compare_all.py`, `ui_check.py`.
- Tests: `backend/testbed/tests/test_testbed.py` - 18 passed (topology counts vs journal Table III, 33-bus ties and numbering, A_hat recomputed on switch change, fault counts, J cost and feasibility, islanding rule, redistribution invariants, weights sum to 1, C_comm formula, dense TA layer == PyG TAGConv).
- Docs: `docs/paper_gap_analysis.md`, `docs/sei_baseline.md`, ARCHITECTURE.md section "Testbed + paper reproduction".

### Baseline before any change (docs/sei_baseline.md)
`npm run build` PASS, `npm run lint` PASS, EnergyLedger Hardhat tests 10 passing. Backend pytest and the existing views could NOT be run: TimescaleDB was not running and Docker Desktop was off. They are re-checked at the end.

### Measured so far (all simulated testbed)
- Conference twin (5 simulated datasets): per-source F1 solar ~0.26-0.43, wind ~0.17-0.28, hydro ~0.88-0.92. The validation tau sweep ended at the edge (tau = 0.9) in all 5 datasets because the FAR <= 1 % constraint was never met; the pre-registered fit (balanced logistic regression) was kept.
- Conference forecasting, first seeds: RMSE ~0.9 kW (R2 ~0.995) for GCN-fixed and TGNN, well below the paper's ~2.65 kW (different nameplate / noise; not tuned).
- Journal TA-GNN, first training runs: demand head generalises (val MSE ~0.012 vs train ~0.001) but the fault head overfits (topology A, iteration 0: train acc 97.5 %, val acc 74 %). Cause (checked, not a bug): the chronological 80/20 split has class counts train [12207, 184, 359, 609, 454] vs val [2826, 384, 134, 0, 112] (no generation-loss events, larger load surges than seen in training). Reported as measured.

### Deviations from the papers / the plan (all logged in PREREGISTRATION.md "Change log", decided before the affected metrics existed)
1. Amendment 1: journal training batch = 32 snapshots (= N for topology C) instead of "batch = N" (A: 6, B: 14); FL local epoch = 5 % of the windows, 100 rounds max.
2. Amendment 2: T_rec uses a "restorable floor" so a scheme that restores nothing is not scored 0 (bug in the first definition, found on a toy run).
3. Amendment 3: FL grid tuned on topology A only; B and C reuse A's selection; C on fewer iterations.
4. Amendment 4 (user asked to finish training in ~1 h): all journal epoch counts x 0.4 (search 10, finals 100 / 100 / 60, scheduler breakpoints 20 / 60); topology C trains on iteration 0 only.

### In progress
- Journal training farm (Tables IV-V: 8 search fits + 4 final fits per topology-iteration) relaunched with the reduced budget.
- Held-out evaluation-scenario datasets for A and B (3 iterations each) and C iteration 0 (done); the Table VIII scenario (20 outages of line 12-13 on topology C).
- Conference forecasting (6 models x 3 seeds).

### Still to do
Twin evaluation (Tables VII-IX), FL grid and finals (Table X), trading + EnergyMarket settlement per topology (needs a Hardhat node; gas/latency measured on an idle machine), conference FL (Table VI) and settlement bench (Table VIII), exports, `comparison.md`, `reasons.json`, Flower parity run, backend pytest + existing-view regression once TimescaleDB is up, headless-browser check of all views, final report.

### Known limitations
- All numbers are from a simulator; the papers' absolute values depend on unpublished normalisation and noise, so a miss is not by itself a defect.
- Reduced epochs / FL budget (above) mean Tables IV, V and X are not run at the papers' literal budgets.
- Gas/latency come from a local Hardhat node, not a public network.
- `backend/testbed/data/` holds large generated datasets; I did not edit `.gitignore` (outside the allowed edits) - consider ignoring it.

### Testbed + paper reproduction - status 2026-10-13
- All paper experiments have now been run on the simulated testbed (journal Tables III-XI, conference Tables II, IV-VIII, figures). Results: `experiments/results/<run_id>/metrics.json`, `experiments/results/comparison.md` (measured vs paper, per-table within-tolerance count), `experiments/results/reasons.json`.
- Regression: backend `pytest tests` 46 passed (TimescaleDB via Docker Desktop), Hardhat 22 passing (10 EnergyLedger unchanged + 12 EnergyMarket), `npm run build` / `npm run lint` clean, testbed tests 18 passed, headless-Chrome check of every view (existing + Results / Topologies / Graphs) with real result files: no console errors.
- Fixes this round: `/testbed/results` served NaN (invalid JSON) for single-iteration metrics -> now null; `export_all.fault_replay` doubled the path (`it0/it0`) -> fixed; `fl_runner tables` skips a cell whose run has not finished; `Market` reads the node URL from `SEI_RPC` (default unchanged).
- Honest outcome: the structural and counting targets (Tables II, III) match; the learned / simulated metrics mostly do **not** land inside +-5 % of the papers' values (see comparison.md and the per-row reasons). Nothing was tuned toward a paper number. Journal Table X rounds-to-target is degenerate (1 for every method) because the centralised reference overfits - PREREGISTRATION disclosure 6.
- Final (2026-10-13 20:55): topology C FedProx run finished; Table X is complete for A, B, C (n = 3 / 3 / 1 iterations). 57 of 282 targets within tolerance.

## UI clean-up (2026-10-20)
- Removed the Results tab (nav entry, App route, `ResultsTab.jsx`); the `/testbed/results` backend route is kept but unused by the UI.
- Removed the explanatory disclaimer paragraphs at the top of the Graphs and Topologies tabs; the pill now reads "Simulated".
- Words "journal" / "conference" / "testbed" are blanked from everything the UI displays: frontend strings plus served graph/topology/redistribution/fault text (`_scrub` in app/api/testbed_routes.py). Identifiers (directory `backend/testbed`, `/testbed/*` URLs, file names) are kept to avoid breaking code.
- Data normalisation: readings carry a `normalized` dict (see ARCHITECTURE.md "Normalized data schema"); node-level frontend views display it. Backend `pytest tests` 46 passed, `vite build` OK.


## Prosumer market (live) (2026-10-20)

Four SIMULATED buildings (prosumers) on a new `community_bus` trade surplus solar for demo credits. Registration ("existence") and
every exchange step are transactions on the unchanged `EnergyMarket` contract (local Hardhat node, next to `EnergyLedger`); each
settled trade is mirrored into the ledger as a `P2P_TRADE` record, so Verify / integrity / the tamper demo cover live trades.
Design and data flow: ARCHITECTURE.md "Prosumer market (live)".

### What was built
- **Backend** (`backend/app/market/`): `prosumers.py` (PV formula, synthetic load profiles, role), `engine.py` (matching, metering
  allocation, settlement amount), `chain.py` (Web3 client + auto-deploy to `blockchain/deployments/localhost-market.json`),
  `service.py` (interval clock + async chain worker + ledger mirror), `store.py` (`market_prosumers`, `market_intervals`,
  `market_orders`, `market_trades`); `app/ingestion/prosumer_source.py` (weather poller + readings); `app/api/market_routes.py`
  (`/market/status|prosumers|prosumers/{id}/series|intervals|intervals/{id}|trades`, all GET, protected, pinned in tests/test_auth.py).
  Prosumers go through the existing pipeline (normalize -> twin update -> persist -> broadcast) and SKIP fault detection.
- **Isolation**: `predictor.score` filters to the original 9-node subgraph before building `edge_index`; `self_healing.maybe_trigger`
  ignores prosumers / community_bus ("prosumer self-healing: future work"); `backend/ai/federated` untouched.
- **Frontend**: Digital Twin map (prosumer cards with role pill, provenance badges, "On-chain ✓ #block" chip, community bus,
  violet dashed -> solid trade edges with "Settled · block #N", thin grey "served by grid" edges), prosumer side panel (24 h chart,
  trades, address), "Prosumer market" strip; Redistribution: market summary card, "Source" column (Live market / Simulated (button)),
  live-market flow cards ("Settled on chain · block #N"); Blockchain explorer: "Prosumer market" section (registrations table, live
  order book, trade journey Registered -> Offer -> Bid -> Matched -> Metered -> Settled -> Mirrored to ledger, each with tx hash /
  block / gas, linking into the existing record detail + Verify) and a "Market events" filter. Vite proxies `/market`.
- Provenance on every value: code comments, API payloads, ledger payloads (`provenance_detail`) and UI badges. "Prosumers are
  simulated buildings: solar estimated from live weather, load synthetic. Amounts are demo credits." is shown on every market view.

### Decisions (as specified)
Prosumers: house 5 kWp, apartment block 15, small shop 10, school 30; role deadband 0.1 kW; community bus capacity 100 kW (default).
Solar = REAL Open-Meteo GHI + temperature (default Chennai), `kW = kWp * GHI/1000 * 0.80 * (1 - 0.004 * max(0, Tcell - 25))`,
`Tcell = Tair + 0.03 GHI` -> provenance `live_api_estimated`; load = deterministic synthetic hourly profile (+-5 % seeded noise) ->
`simulated`; `PROSUMER_IRRADIANCE_OVERRIDE` -> solar provenance `simulated`, UI "Demo irradiance". Per interval
(`MARKET_INTERVAL_SECONDS`): kWh = mean net kW x interval hours; sellers = surplus prosumers (offer = forecast surplus), buyers =
deficit prosumers; offers ascending by ask, bids descending by max, match while ask <= max, `qty = min(remaining)`, **price = the
seller's ask**; unmatched deficit = "served by grid", unmatched surplus = "exported to grid" (UI only). At the end of the interval the
backend (oracle) submits METERED Wh = energy actually delivered from that interval's readings; `settle` pays `p * min(q_s, q_b)`.
Prices are illustrative demo credits (ask 5.0-6.0, max 7.0-8.0 per kWh), not tariffs.

### How to run
Hardhat node (`cd blockchain && npm run node`), TimescaleDB, backend (`cd backend && venv\Scripts\python run.py`), frontend; the
market starts with the backend and registers the 4 prosumers on its own (auto-deploys EnergyMarket if needed). Env vars (`.env`,
all optional, documented in `.env.example`): `PROSUMER_LAT`, `PROSUMER_LON`, `PROSUMER_UTC_OFFSET_HOURS`,
`PROSUMER_IRRADIANCE_OVERRIDE` (dev only, W/m2, e.g. 800 to trade at night), `MARKET_INTERVAL_SECONDS` (default 120),
`COMMUNITY_BUS_CAPACITY_KW` (100), `PROSUMER_ROLE_DEADBAND_KW` (0.1), `MARKET_PRICES` (JSON), `MARKET_ENABLED`. Headless UI check:
`python experiments/market_ui_check.py --email ... --password ... --shots <dir>`.

### Measured gas per step (local Hardhat node, 4 prosumers, ~13 settled intervals; `market_*` tables)
| step | n | min | mean | max |
|---|---|---|---|---|
| register | 4 | 67,915 | 67,936 | 67,975 |
| postOffer | 54 | 78,531 | 78,848 | 95,631 (first write per account) |
| postBid | 26 | 78,598 | 79,256 | 95,698 |
| matchTrade | 37 | 163,929 | 166,670 | 166,751 |
| submitMeter | 26 | 33,521 | 33,521 | 33,521 |
| settle | 26 | 47,176 | 49,163 | 81,392 (first settle credits a fresh balance slot) |
| advanceInterval | 13 | 28,044 | 28,044 | 28,044 |
| deployment (EnergyMarket) | 1 | | 1,540,982 | |

### Verification (2026-10-20, PROSUMER_IRRADIANCE_OVERRIDE=800, MARKET_INTERVAL_SECONDS=60)
- `backend pytest tests`: **67 passed** (46 before + 21 new in `tests/test_market.py`: PV formula, load shape/determinism, deadband,
  matching, settlement, ledger-mirror payload, 9-node isolation, self-healing guard, worker not blocking with the chain down; the
  pinned protected-route list in `tests/test_auth.py` is extended with the 6 `/market` routes). TimescaleDB was running.
- `blockchain npm test`: **22 passing** (EnergyLedger 10 + EnergyMarket 12), contracts and tests unchanged.
- `ai/check_serving_parity.py`: max logit difference **4.77e-07** (baseline 4.8e-07), PARITY OK.
- `GET /twin/nodes`: the original 9 nodes with the same keys + 5 new (`community_bus`, 4 prosumers), 13 edges (8 + 5); `GET /nodes`: 7
  nodes / 6 edges; `GET /twin/decisions` unchanged.
- End to end on the local Hardhat node: 4 registrations on chain (blocks 64-68), 13 settled intervals, 26 settled trades, **26
  mirrored `P2P_TRADE` records, every one verified `match`**; tamper demo -> `mismatch`, restored copy -> `match`; integrity `intact`.
- `npm run build` and `npm run lint` clean. Headless Chrome (`experiments/market_ui_check.py`): 29/29 checks (Digital Twin cards,
  badges, on-chain chips, dashed and settled trade edges, side panel; Redistribution summary, Source column, Blockchain registrations /
  order book / trade journey / Market events; every existing view, no console errors).

### Limits
kW arithmetic, not power flow; synthetic loads and estimated solar (nothing is physically sensed; the ESP32 -> MQTT -> TimescaleDB
path is only a documented seam); local chain only (the market refuses other networks; the prosumer keys are Hardhat's public dev
keys); amounts are demo credits; no prosumer self-healing; the AI excludes prosumers; with 60-120 s intervals the traded energy is a
few tens of Wh per trade; interval count/backlog: while the chain is down at most 3 intervals are queued, later ones are recorded as
`skipped`; a backend restart abandons the interval that was open (its trades stay matched on the contract, never settled).
`mockConsumptionKw` (Analytics mock) could now be wired to prosumer consumption (`GET /market/prosumers/{id}/series`); left as is.

### Other changes this required
`address_lock` (`app/blockchain/chain_client.py`): the ledger and the market both send from account #0 and raced for its nonce
("Nonce too low"), so both take a per-address lock. `Ledger.integrity_check` re-checks once before reporting "missing off-chain":
with live traffic a record mined between reading the rows and counting the chain produced a transient false "MISMATCH".


## Prosumer login + P2P dashboard (2026-10-23)

A prosumer (one per simulated building) can now log in, see their building and place a manual offer/bid on the live market.
Additive: admin routes, the admin dashboard, both contracts and the market's automatic trading are unchanged. Design: ARCHITECTURE.md
"Prosumer login + P2P dashboard".

### What was built
- **Auth**: role `prosumer` + `users.prosumer_node_id` (FK to a new 4-row `prosumer_nodes` table, unique per node). `invites` gained `role` and
  `prosumer_node_id`. Settings -> Admins -> "Invite as" lets an admin pick a building; registering through that link creates a prosumer linked
  to it (a plain invite still creates an admin; a node that already has an account cannot be invited again). `require_prosumer` (401 / 403)
  guards the new router; `require_admin` already 403s prosumers; `GET /auth/me` now answers any signed-in user so the SPA can route by role.
  After login a prosumer lands on `/prosumer`; admins keep `/dashboard`. A prosumer opening `/dashboard/*` is redirected back, an admin
  opening `/prosumer` is sent to the dashboard.
- **Backend** `app/api/p2p_routes.py` (`/p2p`, `dependencies=require_prosumer`, own node only; an optional `node_id` naming another node -> 403):
  `GET /p2p/me`, `GET /p2p/book`, `GET /p2p/trades`, `POST /p2p/offer {kwh, ask}` (only in surplus), `POST /p2p/bid {kwh, max}` (only in
  deficit), `POST /p2p/auto {enabled}` (per-prosumer auto-trade switch, default on; off = the market service skips automatic orders for that node).
- **Frontend** `/prosumer` (`pages/ProsumerPage.jsx`, reuses `src/ui`): header (building, role pill, net kW, balance in demo credits, auto-trade
  switch), "Sell surplus" / "Buy energy" cards (only the one valid for the role is enabled), live order book, "My trades" with a status chip
  (pending -> matched -> settled) and block number, the "Simulated building ..." banner. Live updates through `useMarketSocket({ rest: false })`;
  `/p2p/*` is re-read when a socket message arrives (no polling). Vite proxies `/p2p`.
- **Seeding**: `backend/scripts/create_prosumers.py` (see below).

### Decisions made (flag if you want them changed)
- **A manual order is queued and joins the next interval** (it does not match mid-interval): it replaces that node's automatic order for the
  interval, is capped at the forecast quantity at that moment (so metering can back it) and lapses if the role flipped. One queued order per
  node (a new one replaces it). Then it is the normal pipeline: matching with price = seller's ask, the chain worker (signed by the node's own
  Hardhat dev account), metering, settlement, ledger mirror as `P2P_TRADE`.
- **Quantity** must be > 0 and <= forecast surplus/deficit x one interval (shown as "up to X kWh"). **Price** must lie within the `MARKET_PRICES`
  bounds = [lowest configured ask, highest configured max] (5.0 - 8.0 with the defaults).
- **WebSocket**: prosumer sessions are accepted on `/ws/updates` but receive only `market_*` messages (the manager filters per connection);
  admins still get everything. The order book shows all buildings' open orders (it is a market book); balance/trades/me are own-node only.
- New tables: `prosumer_nodes`, `market_node_settings`, `market_manual_orders`; `market_orders.manual` column (all idempotent migrations).

### Seeded accounts (`create_prosumers.py`)
`cd backend && venv\Scripts\python scripts\create_prosumers.py [--all] [--node prosumer_x_01 ...] [--reset]`. Default: `prosumer_home_01`
(home01@sei.local) and `prosumer_shop_01` (shop01@sei.local); `--all` adds `apartment01@sei.local` and `school01@sei.local`. A random 16-character
password per account (passes the password policy) is printed once as a table; never written to a file, log or .env; only the argon2 hash is
stored. Idempotent: a node with an account is skipped unless `--reset`, which rotates the password and prints the new one. Audit events
`prosumer_created_cli` / `prosumer_password_reset_cli`.

### Verification (2026-10-23; demo run `PROSUMER_IRRADIANCE_OVERRIDE=800 MARKET_INTERVAL_SECONDS=30`)
- `backend pytest tests`: **90 passed** (67 + 23 new in `tests/test_p2p.py`: role separation both ways, another node's data -> 403, quantity/price/side
  validation, queue replacement, auto-trade switch, prosumer invite -> registration, WebSocket market-only filter, the script as a real subprocess:
  refuses duplicates, `--reset` rotates, `--all`, a seeded account logs in, reaches `/p2p/me` and gets 401/403 on admin routes, only the hash is stored).
  The 6 `/p2p` routes are pinned in `tests/test_auth.py`.
- `blockchain npm test`: **22 passing** (contracts untouched). `npm run build` and `npm run lint` clean.
- Headless Chrome, `python experiments/p2p_ui_check.py --email ... --password ...` (shop01): **14/14** - login lands on `/prosumer`, `/dashboard/home` bounces back,
  `/nodes` -> 403, header/banner/live badge, only the Buy card enabled (deficit), 0.01 kWh bid queued -> in the live book as "manual" -> trade pending/matched ->
  **settled with block 178**, and the settle tx receipt on the Hardhat node has status 1 at that block. Auto-trade off: the node placed no automatic order in the next
  two intervals; switched back on afterwards.

### Limits
Local Hardhat dev accounts only (public keys); a manual order can wait up to one interval (120 s default); the book is the current interval's, so
orders disappear from it once the interval is done (they live on in "My trades"); the page shows no history chart.

## Software-only test cases TC01-TC05 (2026-10-23)
All code in `tests/` (see `tests/README.md` for how to run each); no product code changed. Results:

| ID | Result | Observed |
|---|---|---|
| TC01 wind/hydro reading outside limits | **PASS** (after fix) | First run FAILED: no validation step existed (9.9 GW / 400 m/s and -700 MW were stored as-is). At the user's request added `app/ingestion/validation.py` (`validate_live`, called from `ingest_reading`): non-finite or out-of-limit live wind/hydro samples (wind power outside [0, 100 x rated]; hydro power negative; wind speed outside [0, 75] m/s) are logged and replaced by the node's last valid value, or dropped if there is none. Limits are loose sanity bounds on purpose: live power is an estimate. Hydro has NO upper limit: the first version had one (40 MW) and a live Open-Meteo check showed the real hydro estimate is ~49,500 kW, so it would have dropped all live hydro data; fixed and re-verified against the live API (wind and hydro both pass unchanged). SCADA replay and prosumers are untouched. Backend suite still 90 passed; 4 tests in `tests/test_tc01_tc03.py` pass. |
| TC02 switch change in topology C | PASS | Closing TS34 (buses 9-15) changes A at (9,15) 0->1 (32->33 edges), 12 entries of A_hat change; closing TS34 + opening 9-10 changes (9,10) 1->0 and (9,15) 0->1. The same journal_C/it0 `3_LRS` model (weights hash identical before/after) predicted on every topology (finite demand + 5-class output). Caveat: this is the offline simulated-testbed twin (`backend/testbed`); the live app twin is the 9-node graph, not IEEE-33. |
| TC03 prediction service stopped | PASS | Predictor load forced to fail -> `loaded=False`. Temperature 95 C vs a stable baseline -> `fault_predicted`, flagged_by `["rule_based"]`, no ta_gnn verdict, rule-based decision `reduce_load_share 0.5`; a labelled fault -> `fault` + a decision. |
| TC04 prosumer cannot edit records | PASS | 22/22 checks on in-process Hardhat. Trade 0: 120 milli/kWh, metered 3800/3900 Wh, settled, balances +456/-456, Settlement tx `0x665b2c96...950e1d` block 8. Seller and buyer: submitMeter -> `NotGateway`, settle again -> `AlreadySettled`, matchTrade/advanceInterval -> `NotGateway`, setGateway -> `NotOwner`, register again -> `AlreadyRegistered`. Trade, balances, tradeCount and the Settlement event identical afterwards. The ABI has no edit/cancel/delete function. |
| TC05 dashboard during a fault | PASS | Fault injected on Kelmarsh T1 through the real ingestion path: KPIs/alert, AI Insights flag, self-healing log, topology panel, blockchain log each updated 48-254 ms after injection (limit 5 s). Screenshots + `tc05_timings.json` in `tests/screenshots/`. |

Test-environment notes: TC05 used a synthetic healthy feed instead of the SCADA replay (the replay starts inside a logged fault) and a test-only inject route in `tests/tc05_server.py`, on an isolated DB / Hardhat node / ports; the "blockchain log" time is when the record appears in the dashboard (WebSocket), the Hardhat node mines instantly.

## Software-only test cases, second sheet "Set-2 TC01-TC10" (2026-10-23)
Run on top of TC01-TC05 above (same IDs, different cases, hence the "Set-2" prefix). Files and run commands: `tests/README.md` "Set 2". The sheet's
"Actual Output" figures (7.42 vs 8.50 kW, 96.0 vs 145.0 s, 42 vs 85/62 rounds, 105,300 gas, cost 0.42) are paper-style targets; the table gives what this
repo MEASURED. Pass criterion = the qualitative expected output.

| ID | Result | Observed |
|---|---|---|
| Set-2 TC01 sensor reading outside limits | PASS | Re-ran the existing 4 tests: 9.9 GW / 400 m/s wind and -700 MW hydro are flagged invalid (warning logged) and replaced by the last valid value. |
| Set-2 TC02 broker unreachable during publish | PASS (after adding code) | First FAILED by absence: there is no MQTT publish path in the product (ESP32 -> Mosquitto is only a documented seam). Added `app/ingestion/buffered_publisher.py` (stdlib only, no new dependency, imported by nothing, so existing behaviour cannot change): bounded FIFO store-and-forward around an injected `send`. Tested against a fake broker: 2 messages published while down were buffered, re-sent in order on the next publish after reconnection; buffer bound + drop count tested. NOT yet wired to a real Mosquitto client. |
| Set-2 TC03 prediction service stopped | PASS | Existing test: predictor not loaded -> rule-based flag + `reduce_load_share 0.5`; labelled fault -> `fault`. |
| Set-2 TC04 demand forecast, topology C, TA-GNN vs GCN | PASS | Saved topology-C models run live on the held-out `eval` scenario: MAE 6.47 kW (TA-GNN 3_LRS) vs 17.76 kW (GCN). Stored validation-split figures (comparison.md J Table VI/IX): 7.81 vs 22.53 kW. Not 7.42 vs 8.50: the sheet's numbers are paper values. Simulated testbed. |
| Set-2 TC05 line outage between buses 12-13 | PASS | 20 outages evaluated live (173 candidate actions, 2 infeasible): chosen = the feasible candidate with the lowest J (0.05): open the faulted line 12-13 and close tie switch TS34 (`open+close_tie`). Over all 20 outages the twin picked `open+close_tie` via TS34 or `open+island`. Measured cost 0.05, not the sheet's 0.42 (J Table VIII `example_cost` is "outside tolerance"). |
| Set-2 TC06 20 injected faults, topology C | PASS | Same 20 outages: mean T_rec twin 23.8 s vs rule-based (default) 34.2 s (all 20 interrupted); unserved energy 59.8 vs 84.9 kWh. Not 96.0 vs 145.0 s. Caveat already in comparison.md: on the 60-fault `eval` set for topology C the twin is SLOWER (135 s vs 56 s, -143 %), so this PASS holds for this scenario only. |
| Set-2 TC07 federated training, 33 clients | **FAIL** (not altered) | Read from the stored run (`j_table10`, not re-trained: hours). Rounds to the validation-loss target: 1 / 1 / 1 for FedAvg / FedProx / adaptive FedProx (degenerate, PREREGISTRATION disclosure 6). Rounds to a common target: FedAvg never reached it, FedProx 44, adaptive FedProx 49, so adaptive is NOT faster than FedProx. Not 42 vs 85 and 62. Left as is: making it pass would mean tuning toward a paper number, which the project rules forbid. |
| Set-2 TC08 register, offer, bid, match, settle | PASS | `Registered`, `OfferPosted`, `BidPosted`, `TradeMatched`, `Metered`, `Settled` all emitted; trade settled, balances +456/-456. Gas: register 67,855, postOffer 95,631, postBid 95,698, matchTrade 144,027 (highest), submitMeter 33,533, settle 81,364 (not 105,300 for settlement). |
| Set-2 TC09 offer from unregistered account | PASS | `postOffer` and `postBid` from an unregistered account revert with `NotRegistered()`; offer/bid counts unchanged. |
| Set-2 TC10 dashboard during a fault | PASS (result reused) | Same test as the first sheet's TC05, run earlier today, not re-run: measurements 71 ms, fault prediction 74 ms, topology 78 ms, blockchain log 155 ms, self-healing log 254 ms after injection (limit 5 s; the SCADA feed interval is 2 s). Code since then only gained the unused `buffered_publisher.py`. |

Product code changed: only the new `app/ingestion/buffered_publisher.py`. Backend suite after the change: 90 passed. Hardhat `blockchain/deployments/` unchanged.

## Solar plant source (2026-10-24)
- Added `solar_01` (50 kWp) replaying a small bundled sample CSV (`backend/data/solar/solar_plant_sample.csv`, 24 hourly rows,
  illustrative not measured) via `app/ingestion/solar_source.py`; `NormalizedReading.type` gains `"solar"`; twin node gated by
  `with_solar` on the live singleton only (AI 9-node topology unchanged); added to Module 1 `twin` graph too.
- Settings: `SOLAR_SOURCE=replay|sensed`, `SOLAR_REPLAY_SECONDS`. ESP32 hook: `solar_source.ingest_sensed()` (MQTT subscriber not built).
- Frontend: restored the Solar group/filter in SourcesTab (was blanked in the working tree), "Solar plant" card name.
- Tests: `backend/tests/test_solar.py`; `test_market.py` node-set expectation now includes `solar_01`. Full backend suite: 93 passed.
- Not checked in a browser.

## Stop/resume data per node (2026-10-24)
- Settings -> System -> "Live data" card lists every streaming node (not `grid`) with a "Stop data" / "Resume data" button.
- Backend: `app/ingestion/pipeline.py` keeps an in-memory `_stopped` set; `ingest_reading` drops readings for stopped nodes, so it
  covers every source (live poller, SCADA replay, solar). `app/api/routes.py`: `GET /nodes/stream` -> `{stopped: [...]}`,
  `POST /nodes/{id}/stream/{stop|start}` (admin only, 404 for unknown node/action).
- State is not persisted: a backend restart resumes all streams. Prosumer nodes are not listed (not in `GET /nodes`).
- Not tested or checked in a browser.

## solar_hardware (real ESP32 + INA219 node) (2026-10-24)
- Added firmware (`firmware/solar_hardware/solar_hardware.ino`), serial ingestion (`backend/app/ingestion/solar_hardware.py`, enabled by
  `SOLAR_HARDWARE_PORT`), node `solar_hardware` in the live twin and Module 1 graph, `backend/scripts/capture_solar_hardware.py` (time-limited
  capture), and `backend/testbed/hardware_node.py` (hardware leaf for topologies A/B/C; default `build()` unchanged). `pyserial==3.5` added.
- Tests: `backend/tests/test_solar_hardware.py`, `backend/testbed/tests/test_hardware_node.py`; `test_market.py` node set now includes `solar_hardware`.
- Placements chosen by me, the docs gave none: A node 2, B node 4, C bus 10 (reasons in ARCHITECTURE.md). Per-unit rating is now the real 0.526 W (see the later entry).
- Hardware bring-up: CP210x driver installed, board on COM5. The board runs the user's `arduino.c` (MQTT + Wi-Fi, placeholder credentials),
  not firmware/solar_hardware. 45 s capture (no board reset): 9 samples, 5 s apart (`backend/data/solar_hardware/capture.jsonl`):
  bus 0.856-0.864 V, current -0.1..0.0 mA, power -0.1..0.0 mW.
- NOT VERIFIED: those values are NOT plausible for a lit panel into 68 ohm (~12 mA expected at 0.86 V): panel in the dark or the circuit not
  closed through VIN+/VIN-. firmware/solar_hardware/*.ino was never compiled or uploaded (ESP32 core install via arduino-cli still downloading).
  The live backend ingest from COM5, a browser check, and (panel rating now 0.526 W, resolved) are not done.
- MQTT subscriber + Mosquitto service added (see ARCHITECTURE.md); verified with a published test message through a real broker (6 tests pass), NOT with the real ESP32.
- Normalised voltage/current added (`normalized.voltage|current`), Sources tab card for solar_hardware (frontend builds; NOT viewed in a browser). Real COM5 data through `ingest_reading` verified: bus 0.864 V -> normalized.voltage 0.108, power 0.

## solar_hardware: panel rating + online wiring (2026-10-24, later)
- **"Live values 0.00" diagnosed.** Probed the running backend (`GET /twin/nodes`): wind_01, hydro_01, solar_01 and the prosumers had real non-zero
  values; the Kelmarsh turbines read 0.0 p.u. only while their replayed 2016 data is in real "Stop" events. The node that was truly empty was
  `solar_hardware` (no reading at all) because `SOLAR_HARDWARE_PORT` was not set in `.env`, so nothing read the board and the dashboard fell back to 0.
- **Panel rating set to the real one:** 70x70 mm panel, 0.526 W (the earlier "526 W" was read as 0.526 W). `SOLAR_HARDWARE_RATED_KW` = 0.000526 in
  `app/twin/digital_twin.py`; `testbed/hardware_node.py:RATED_MW` = 526.0 (mW; the old 5.0 was 1000x too small for its own 5 W placeholder, since it is in mW); `test_load_pu_series` fixture rescaled (0/263/900 mW -> 0/0.5/1.0 p.u.).
  Backend solar/market tests (27) and testbed hardware tests (7) pass.
- **Made it online (config):** `SOLAR_HARDWARE_PORT=COM5` added to `.env` (and a blank entry to `.env.example`); Sources tab now labels the
  hardware card "Sensed - ESP32 + INA219" even while offline (it used to say "Live API").
- **NOT online yet - hardware/OS side, not fixed:** COM5 cannot be opened: from a script "A device attached to the system is not functioning",
  from the restarted backend "Access is denied". The backend retries every 5 s, so it will connect by itself once the port is free. Needs: unplug/replug
  the ESP32 (and close any serial monitor), then make sure only ONE backend is running. A stray older uvicorn worker (pid 24988, orphan of the
  previous dev server) was still listening on :8000 after the restart; I was not permitted to kill it, so stop it manually.
- Still NOT verified: any real INA219 reading through the backend this session; earlier captures were ~0 mA (panel dark or circuit open), so even
  when online expect ~0 until the panel is lit and the loop VIN+ -> VIN- -> 10 ohm is closed.
- Load resistor is **10 ohm**, not 68 ohm (user correction). Backend now reads COM5 and stores a solar_hardware row every 5 s, but values are still ~0 mW
  (0.0-0.3 mW) with the 10 ohm load: a lit panel would give roughly 0.1 W-class mW readings (<=~50 mA), so the panel is dark or the VIN+/VIN- loop is open.

## 8 nodes showing data / Sources tab solar card (2026-10-24, later)
- "2/8 active" cause: (1) several backend stacks were listening on :8000 at once (the old dev server's orphan worker, one I started, one started
  later), so the browser hit a stale one with few readings; (2) the wind/hydro first poll failed (`getaddrinfo failed`, no network at startup) and
  then waited a full 60 s. **Fix in code:** `app/ingestion/poller.py` retries after 10 s when a poll failed. **Fix by hand (not done by me, process
  kills were refused):** stop every backend and start exactly one `python run.py`; the 4 Kelmarsh nodes appear within ~8 s (round-robin, 2 s each).
- Sources tab: the "Solar hardware" card now always shows Voltage / Current / Power (p.u. + raw V, mA, mW, 2 decimals), dashes while no reading,
  fed by the existing WebSocket. Frontend builds; NOT viewed in a browser.


## Self-Healing Analytics tab (2026-10-26)
- Added sidebar view "Self-Healing" (`/dashboard/healing`): summary panel, topology overlay graph, per-event table. Live 9-node twin events come from the new
  `backend/app/twin/healing_events.py` (hooked into `self_healing._handle_fault`, WS `healing_event`, `GET /twin/healing-events`); A / B / C replay the saved fault
  scenarios from `/testbed` at 25x (simulated, labelled). Details in ARCHITECTURE.md "Self-Healing Analytics tab".
- Files added: `frontend/src/tabs/SelfHealingTab.jsx`, `backend/app/twin/healing_events.py`. Changed (additive): `self_healing.py`, `twin_routes.py`, `useDigitalTwinSocket.js`
  (extra `healingEvents` return field), `App.jsx`, `ui/nav.js`, `backend/tests/test_auth.py` (route pin).
- Verified: frontend builds, oxlint clean, backend imports, and a forced fault on the twin produced a correct `restored` event (detect 21 ms, compute 0.1 ms).
  NOT done: viewing the tab in a browser; `tests/test_auth.py` hung when run here (needs the DB/stack), so the route-pin test was not run.
- Known limits: A/B/C times are the saved simulation's, not live; the 0.5 s switch time is assumed; solar nodes cannot raise events.

## Self-healing UI: switch actions, ETA, click-to-play reroute (2026-10-26)
- `frontend/src/tabs/SelfHealingTab.jsx`: new "Switch actions & estimated healing" card for the selected event (ordered OPEN/CLOSE
  list with done/pending, plus estimated/remaining heal time). Live 9-node events derive ops from `path.isolated_lines` / `path.lines`;
  A/B/C derive them by diffing line status between the fault stage and the "Action applied" stage (isolate first, then close ties).
- Clicking a row in A/B/C plays the reroute (~2.5 s: fault → rerouting with animated green path → restored) while ops tick to "done".
- `frontend/src/tabs/TopologiesTab.jsx` Fault replay lists the switch actions applied up to the current step.
- Removed the word "Simulated" from the UI of the three topologies (SimPill no longer rendered; notes reworded). Backend untouched.
- Re-feeding unsupplied buses (A/B/C replay, `deriveSim` in SelfHealingTab.jsx): if a bus is still dead after the recorded action
  (e.g. B bus 10, C buses 16-17), the replay now closes an open non-faulted line/tie that links it to a supplied bus (repeating
  outward), draws the new green path and adds the CLOSE step to the switch list. Display-side only; saved results and backend unchanged.

## Live protection: overload reroute, node isolation, line-fault sectionalising (2026-10-26)
- **New** `backend/app/twin/grid_protection.py` (engine), extended `healing_events.py` (events now carry `kind`, `why`, `decision`, ordered `steps`, `impact`, incident
  lifecycle), small additive helpers in `digital_twin.py` (`set_bus_capacity`, `bus_capacity_kw`, `set_uplink`, bus attr `uplink_closed`), new routes
  `POST /twin/healing/simulate` and `POST /twin/healing/repair` (admin-protected, pinned in `tests/test_auth.py`), `check_overloads()` called from `self_healing.maybe_trigger`.
- **Bus overloaded -> reroute:** the plan enumerates which sources to move to the other bus (open feeder, close tie) and picks the one with the least unserved kW (ties:
  fewer switch ops); what the other bus cannot take is curtailed (biggest source first). Bus load is rated x share (no power flow), as elsewhere in the twin.
- **Faulty node -> isolate until fixed:** `self_healing._handle_fault` now always chooses `isolate` (open both ends of the feeder). The other candidates are still scored and
  logged. When the health status clears, `_handle_recovery` closes the switches and reconnects the node to its primary bus (event `incident: repaired`). This CHANGES the old
  behaviour, where the lowest-score candidate (usually a reroute onto the other bus) was applied to a faulty node.
- **Faulty line -> isolate, re-feed:** feeder (`source>bus`) or bus uplink (`bus>grid`). Open the switch at BOTH ends, then close the tie switch(es) so the healthy sources that
  lost their path are fed from the other bus; whatever does not fit in its headroom is curtailed (>= 10 % share) or left unserved. Repair closes the ends and opens the ties again.
- **Live + timing:** simulated faults are injected from the Self-Healing tab ("Fault simulator", severity slider for the overload). Switch steps are EXECUTED one every
  `SWITCH_OP_MS` (0.5 s, assumed - no switch hardware), so the graph, bus meters and step list change live; detect / analyse (compute) times are measured; fault -> restored
  is the measured wall-clock total. New "Why, when and how long" card (reason, clock times, Detect/Analyse/Switching bar with a live elapsed timer, kW re-routed vs unserved,
  bus load before -> after) and a "Healing insights" card (per kind counts / averages, total re-routed, longest).
- **Tests:** `backend/tests/test_grid_protection.py` (6, incl. the HTTP routes, all pass); full backend suite: 103 passed (before the 6th test was added) with the pin test deselected. Frontend builds, oxlint clean. Real-fault path checked
  by forcing a Kelmarsh fault: isolated on fault, reconnected on recovery.
- **Not done / limits:** NOT viewed in a browser. Only injected faults can be line faults or overloads (no line sensors, loads do not vary on their own); real faults still come from
  the replayed Kelmarsh turbines. Engine events are not written to the blockchain ledger (real node faults still are, as before). Open incidents are in memory (lost on restart).
  With the demo capacities Bus B only has 500 kW headroom, so a bus_b overload only reroutes (part of) a turbine at large severity (about 35 %+); at 25 % it curtails in place.
- **Pre-existing, not touched:** `tests/test_auth.py::test_every_non_public_route_requires_auth` already failed before this change because `GET /nodes/stream` and
  `POST /nodes/{id}/stream/{x}` are missing from its pin list; the two new routes are pinned.

## Live protection follow-up: simulator removed, spare buses, fault reason + recovery time (2026-10-26)
- **Fault simulator removed** from the Self-Healing tab and the HTTP API (`POST /twin/healing/simulate` and `/repair` are gone; pin list in `tests/test_auth.py` updated). The engine functions
  `grid_protection.simulate()/repair()` stay (used by `tests/test_grid_protection.py`, not exposed). The tab now shows "Bus loads and open incidents" (read-only) instead.
- **Two more buses, `bus_c` and `bus_d`** (3000 kW each, live singleton only via `DigitalTwin(extra_buses=True)`; fresh `DigitalTwin()` for AI stays the 9-node graph). They have no source of their own: every
  source's `possible_connections` is now `[primary, old other bus, bus_c, bus_d]`. `grid_protection._alt(bus)` picks the target bus with the MOST headroom, so overload relief, feeder and uplink faults now
  re-feed onto bus_c / bus_d first. `digital_twin.bus_ids()` lists the collector buses. Overloaded bus -> reroute is unchanged in logic (`check_overloads`, after every reading); it is now automatic only,
  and with rated x share loads nothing overloads a bus on its own - the only way to trigger it now is a limit/load change (tests call `simulate()`).
- **Why faulty + time to recover** (real faults, `self_healing._handle_fault`): `why` now states the cause (ground-truth SCADA label / statistical threshold / TA-GNN forecast). New `recovery` field on the event
  `{expected_s, ends_at, basis}`: from the Kelmarsh status-log "Stop" window of that turbine (`scada_replay.FAULT_WINDOWS`, `recovery_estimate`) translated to replay time (rows left x 2 s x 4 turbines;
  10-min SCADA rows), else the median of that node's earlier repaired outages, else none ("recovery time unknown"). The tab shows a live countdown and, after repair, the actual fault-to-repair time.
- **Tests:** `test_grid_protection.py` adapted (+ extra-bus test, route test dropped), `test_market.py` node-set test now includes bus_c / bus_d. Backend: 105 pass; only the pre-existing
  `test_every_non_public_route_requires_auth` (stream routes missing from its pin list) still fails. Frontend builds, oxlint clean. NOT viewed in a browser.


## Dashboard buffers + simpler Self-Healing tab (2026-10-27)
- Dashboard "Energy flow" series and "Live data stream" now live in a module-level store in `frontend/src/tabs/DashboardTab.jsx`, so leaving and returning to the tab no longer restarts them. They are cleared only by `resetLiveBuffers()`, called from `AuthProvider` on login and logout (a server restart reloads the page, which also clears them).
- Self-Healing tab (live view) rewritten for readability: "Faults and rerouting" cards (what is faulty, which source moved from which bus to which, or "disconnected (isolated)", recovery countdown), bus load meters, the grid map, and everything else (switch steps, timings, insights, event table) folded into a "Technical details" section. `routesOf()` derives the moves from the event's `path`.
- Not done / unverified: not viewed in a browser; no login bug was reproduced or changed (none was described); overload still needs a load/limit change to trigger because nothing varies on its own.

## Demand cycle, extra nodes, mesh layout (2026-10-27)
- `app/twin/load_profile.py`: `digital_twin.demand_factor` = 1 + 0.12 sin(2 pi t / 240 s) (env `LOAD_PROFILE_PERIOD_S`, `LOAD_PROFILE_AMPLITUDE`; period 0 = off). Included in `bus_load_kw` and `grid_protection._contrib`. At the peak bus A / bus B pass their limits, protection reroutes sources to bus C / D by itself, and `grid_protection.auto_recover()` repairs those (non-injected) incidents once the home bus fits again (< 97 % of limit). Default factor is 1.0, so tests / AI training are unchanged (the loop only runs in the app lifespan).
- Extra simulated sources on the live twin only (`EXTRA_SOURCE_NODES`, `extra_nodes=True`): `solar_02` (120 kW, bus C) and `battery_01` (500 kW, bus D; output follows the demand peak). Fed by `app/twin/extra_sources.py` straight into the digital twin (no Module 1 graph, DB, AI or fault detection). The battery is a source that can be moved / isolated like the others; it does NOT actively discharge to relieve a bus.
- Dashboard "Total consumption" now = sum of the collector-bus loads (twin model, not metered); mock tag removed.
- Self-Healing graph is laid out as a mesh (buses + grid in the centre, sources around, a dashed tie from every source to every bus). The backend still has no bus-to-bus links.
- Backend tests: 104 pass (one pre-existing auth test deselected). `test_market` expected live-only node set updated. UI not viewed in a browser.

## Node layout fix + live Self-Healing map (2026-10-27)
- **Overlap fixed:** `solar_01`, `solar_hardware`, `solar_02` and `battery_01` had no entry in the fixed layouts, so they fell back to (0,0) and stacked on `wind_01`. Added positions in `components/TopologyView.jsx` (Live Data) and `components/DigitalTwinTopology.jsx` (Digital Twin; the prosumer column and `community_bus` moved down to make room). The Self-Healing mesh (`LIVE_POS`) already had positions. A/B/C (Topologies tab, positions from the backend) not touched.
- **Self-Healing "Live 9-node" renamed "Live nodes"** (segmented label, map aria-label, code comment). Event-source wording in ARCHITECTURE.md left as is.
- **Live map:** node cards show the current output (kW x load share); a closed feeder is animated and coloured while its source produces; a new incident automatically takes over the map (clicking a row still pins an older one); the map refits when the node set changes. All from the existing twin WebSocket, no backend change. A/B/C stay saved-scenario replays (no live stream exists for them).
- Frontend builds; oxlint shows only the 2 older warnings (`Incidents` unused, `DashboardTab` fast-refresh). Backend untouched. NOT viewed in a browser.
