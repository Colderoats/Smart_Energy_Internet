import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, Handle, Position, ReactFlow, useReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { apiFetch } from '../auth/api'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import { SourceIcon } from '../ui/icons'
import { Button, Card, EmptyState, Pill, Segmented, StatCard } from '../ui/components'
import { SOURCE_COLORS, STATUS_COLORS, nodeLabel } from '../ui/theme'
import { ErrorNote, Loading } from '../testbed/common'
import { useTestbed } from '../testbed/useTestbed'

// Self-Healing Analytics. One event table + summary + topology overlay for four topologies:
//  - Live nodes twin (incl. solar_01 and the solar hardware node): events come from the backend
//    (app/twin/healing_events.py) over the existing /ws/updates socket via useDigitalTwinSocket.
//  - A radial / B meshed / C IEEE 33-bus: no live stream exists for these (they are saved simulation
//    results), so the saved fault scenarios (/testbed/topologies/{A,B,C}/faults) are replayed in real time
//    (SIM_SPEED seconds per real second).
// Overlay: red = faulted element, grey = isolated section, animated green = new path.

const TOPS = [
  { id: 'live', label: 'Live nodes' },
  { id: 'A', label: 'A Radial' },
  { id: 'B', label: 'B Meshed' },
  { id: 'C', label: 'C IEEE 33-bus' },
]
const SIM_SPEED = 25 // simulated seconds per real second
const TICK_MS = 200
const GAP_S = 20 // simulated seconds between replayed scenarios
const RED = STATUS_COLORS.bad
const GREEN = STATUS_COLORS.ok
const GREY = '#94a3b8'
const FAULT_TYPES = { 1: 'Line outage', 2: 'Feeder short circuit', 3: 'Loss of generation (node outage)', 4: 'Load surge (overload)' }
const KIND_ICON = { solar: 'solar', wind: 'wind', hydro: 'hydro', grid: 'grid', load: 'bus', collector: 'bus', bus: 'bus' }
const STATUS_TONE = { detected: 'warn', rerouting: 'info', restored: 'ok' }

const fmtT = (s) => (s == null ? '—' : s < 1 ? `${(s * 1000).toFixed(s < 0.01 ? 1 : 0)} ms` : `${s < 10 ? s.toFixed(2) : s.toFixed(1)} s`)
const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null)

// ---------- graph ----------

function HealNode({ data }) {
  const ring = data.fault ? RED : data.warn ? '#f59e0b' : data.grey ? GREY : data.onPath ? GREEN : '#e2e8f0'
  const color = SOURCE_COLORS[data.type] ?? '#64748b'
  return (
    <div className="min-w-[92px] rounded-xl border-2 bg-white px-2 py-1.5 text-slate-800 shadow-sm" style={{ borderColor: ring, opacity: data.grey && !data.fault ? 0.55 : 1, boxShadow: data.fault ? `0 0 0 3px ${RED}33` : undefined }}>
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <div className="flex items-center gap-1.5">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg" style={{ background: `${color}1f`, color }}>
          <SourceIcon type={KIND_ICON[data.type] ?? data.type} size={14} />
        </span>
        <div className="leading-tight">
          <div className="text-[11px] font-semibold">{data.label}</div>
          {data.sub && <div className="text-[10px] text-slate-500">{data.sub}</div>}
        </div>
      </div>
    </div>
  )
}
const nodeTypes = { heal: HealNode }

const edge = (id, source, target, { color = GREY, width = 1.5, dashed = false, animated = false, label } = {}) => ({
  id, source, target, animated, label, labelStyle: { fontSize: 9, fill: color },
  style: { stroke: color, strokeWidth: width, strokeDasharray: dashed ? '5 4' : undefined },
})

// Re-fits the view (debounced) when the node count changes, e.g. nodes arriving over the socket after mount.
function Refit({ count }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    const id = setTimeout(() => fitView({ padding: 0.12, duration: 200 }), 250)
    return () => clearTimeout(id)
  }, [count, fitView])
  return null
}

function Canvas({ nodes, edges, label }) {
  return (
    <div className="h-[520px] rounded-xl border border-slate-200 bg-slate-50" role="img" aria-label={label}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12 }} nodesConnectable={false} nodesDraggable={false} proOptions={{ hideAttribution: true }} minZoom={0.2}>
        <Background color="#e2e8f0" gap={24} />
        <Controls showInteractive={false} />
        <Refit count={nodes.length} />
      </ReactFlow>
    </div>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
      <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: RED }} />faulted element</span>
      <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: GREY }} />isolated section</span>
      <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5" style={{ background: GREEN }} />new (rerouted) path, animated</span>
    </div>
  )
}

// ---------- live 9-node ----------

// Mesh layout: the four buses and the grid in the middle, the sources around them. Every source has a tie to every bus
// (dashed lines), so the picture is a mesh rather than a tree.
const LIVE_POS = {
  grid: [380, 250],
  bus_a: [190, 120], bus_b: [570, 120], bus_c: [190, 380], bus_d: [570, 380],
  wind_01: [0, -40], hydro_01: [200, -40], wind_scada_kelmarsh_1: [400, -40], wind_scada_kelmarsh_2: [600, -40],
  wind_scada_kelmarsh_3: [800, 120], wind_scada_kelmarsh_4: [800, 250],
  solar_01: [800, 380], solar_hardware: [600, 540], solar_02: [400, 540], battery_01: [200, 540], 
}
const AMBER = '#f59e0b'
const LIVE_BUSES = ['bus_a', 'bus_b', 'bus_c', 'bus_d']
const KIND_LABEL = { bus_overload: 'Bus overload', node_fault: 'Faulty node', line_fault: 'Faulty line' }
const OP_TONE = { OPEN: 'bg-red-100 text-red-700', CLOSE: 'bg-emerald-100 text-emerald-700', CURTAIL: 'bg-amber-100 text-amber-700' }

function useNow(ms = 200) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(id) }, [ms])
  return now
}
const clock = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${d.toLocaleTimeString([], { hour12: false })}.${String(d.getMilliseconds()).padStart(3, '0')}`
}
const kw = (v) => (v == null ? '—' : `${Math.round(v).toLocaleString()} kW`)
const lineName = (t) => String(t).split('>').map(nodeLabel).join(' → ')

function liveGraph(twinNodes, ev) {
  const live = ev && ev.incident !== 'repaired' ? ev : null // a repaired incident leaves no overlay: the grid is back to normal
  const path = live?.path
  const pathNodes = new Set(path ? path.lines.flat() : [])
  const nodes = Object.values(twinNodes)
    .filter((n) => LIVE_POS[n.node_id])
    .map((n) => {
      const isBus = n.type === 'bus'
      const overloaded = isBus && n.current_load_kw > n.capacity_kw + 1e-6
      let sub
      if (isBus) sub = `${Math.round(n.current_load_kw).toLocaleString()} / ${Math.round(n.capacity_kw).toLocaleString()} kW`
      else if (n.type === 'grid') sub = undefined
      else if (n.isolated) sub = 'ISOLATED'
      else if (n.load_share < 1) sub = `curtailed ${Math.round(n.load_share * 100)}%`
      else {
        const base = n.node_id === 'solar_hardware' ? 'ESP32 sensed' : n.source_type === 'live' ? 'Live' : 'Replayed'
        const out = n.latest_reading?.power_output
        sub = out == null ? base : `${base} · ${Math.round(out * (n.load_share ?? 1)).toLocaleString()} kW`
      }
      return {
        id: n.node_id, type: 'heal', draggable: false,
        position: { x: LIVE_POS[n.node_id][0], y: LIVE_POS[n.node_id][1] },
        data: {
          type: n.type, label: nodeLabel(n.node_id), sub,
          fault: !!live && live.fixture === n.node_id && live.kind !== 'line_fault',
          warn: overloaded,
          grey: !!n.isolated,
          onPath: pathNodes.has(n.node_id) && live?.fixture !== n.node_id,
        },
      }
    })
  const pathKeys = new Set((path?.lines ?? []).map(([a, b]) => `${a}>${b}`))
  const edges = []
  const drawn = new Set()
  const add = (e) => { edges.push(e); drawn.add(`${e.source}>${e.target}`) }
  for (const n of Object.values(twinNodes)) {
    if (!LIVE_POS[n.node_id] || n.type === 'grid') continue
    if (n.type === 'bus') {
      if (n.uplink_closed === false) add(edge(`${n.node_id}>grid`, n.node_id, 'grid', { color: RED, dashed: true, width: 2.5, label: 'OPEN (faulted line)' }))
      else add(edge(`${n.node_id}>grid`, n.node_id, 'grid', pathKeys.has(`${n.node_id}>grid`) ? { color: GREEN, width: 3.5, animated: true } : {}))
      continue
    }
    for (const via of n.possible_connections ?? []) {
      const key = `${n.node_id}>${via}`
      if (n.active_connection === via) {
        const tied = via !== n.possible_connections[0]
        if (pathKeys.has(key)) add(edge(key, n.node_id, via, { color: GREEN, width: 3.5, animated: true, label: tied ? 'tie closed' : undefined }))
        else {
          // Live flow: animate the closed feeder while the source is actually producing.
          const flowing = !n.isolated && (n.latest_reading?.power_output ?? 0) > 0
          add(edge(key, n.node_id, via, tied ? { color: GREEN, width: 2, label: 'tie closed', animated: flowing } : { color: flowing ? SOURCE_COLORS[n.type] ?? GREY : GREY, width: flowing ? 2 : 1.5, animated: flowing }))
        }
      } else if (!(path?.isolated_lines ?? []).some(([a, b]) => a === n.node_id && b === via)) {
        add(edge(`tie-${key}`, n.node_id, via, { color: '#cbd5e1', dashed: true, width: 1 })) // normally-open tie switch
      }
    }
  }
  for (const [a, b] of path?.lines ?? []) if (!drawn.has(`${a}>${b}`)) add(edge(`${a}>${b}`, a, b, { color: GREEN, width: 3.5, animated: true }))
  for (const [a, b] of path?.isolated_lines ?? []) if (!drawn.has(`${a}>${b}`)) edges.push(edge(`iso-${a}>${b}`, a, b, { color: RED, dashed: true, width: 2, label: 'opened' }))
  return { nodes, edges }
}

function normLive(e) {
  const p = e.path
  const steps = e.steps ?? []
  const fallbackPath = !p ? '—' : p.to ? `${nodeLabel(p.from)} → ${nodeLabel(p.via)} → ${nodeLabel(p.to)} (${p.lines.map(([a, b]) => `${nodeLabel(a)}–${nodeLabel(b)}`).join(', ')})` : `${nodeLabel(p.from)} isolated (no path)`
  return {
    id: e.id, problem: e.problem, fixture: lineName(e.fixture), status: e.status,
    detect_s: e.detect_ms == null ? null : e.detect_ms / 1000,
    reroute_s: e.reroute_ms == null ? null : e.reroute_ms / 1000,
    est_s: e.est_complete_ms == null ? null : e.est_complete_ms / 1000,
    restore_s: e.status === 'restored' ? e.est_complete_ms / 1000 : null,
    pathText: e.decision ?? fallbackPath, action: e.action, raw: e,
    shown: steps.filter((s) => s.state === 'done').length,
    switchOps: steps.length ? steps.map((s) => ({ op: s.op, text: s.text })) : [
      ...(p?.isolated_lines ?? []).map(([a, b]) => ({ op: 'OPEN', text: `Open switch ${nodeLabel(a)}–${nodeLabel(b)} (isolate fault)` })),
      ...(p?.to ? p.lines.map(([a, b]) => ({ op: 'CLOSE', text: `Close / route ${nodeLabel(a)}–${nodeLabel(b)}` })) : []),
    ],
  }
}

function BusMeters({ nodes }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {LIVE_BUSES.map((id) => {
        const b = nodes[id]
        if (!b) return null
        const pct = Math.min(100, (b.current_load_kw / b.capacity_kw) * 100)
        const over = b.current_load_kw > b.capacity_kw + 1e-6
        return (
          <div key={id}>
            <div className="mb-1 flex justify-between text-xs text-slate-600">
              <span className="font-medium">{nodeLabel(id)}{b.uplink_closed === false && <span className="ml-2 text-red-600">uplink OPEN</span>}</span>
              <span className="tabular-nums">{kw(b.current_load_kw)} / {kw(b.capacity_kw)}</span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full transition-all duration-300" style={{ width: `${pct}%`, background: over ? RED : pct > 90 ? AMBER : GREEN }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Incidents({ nodes, events }) {
  const open = events.filter((e) => e.incident === 'active' || e.incident === 'repairing')
  return (
    <Card title="Bus loads and open incidents" subtitle="Rated output x load share per bus. An overloaded bus is relieved by moving sources over a tie switch to the bus with the most headroom (bus C / bus D are spare buses).">
      <div className="space-y-4">
        <BusMeters nodes={nodes} />
        {open.length === 0 ? <p className="text-xs text-slate-500">No open incident. A faulty node is isolated and reconnected by itself when its fault clears.</p> : (
          <div className="space-y-1.5">
            {open.map((e) => (
              <div key={e.id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs">
                <Pill tone="bad">{KIND_LABEL[e.kind] ?? e.problem}</Pill>
                <span className="font-medium text-slate-800">{lineName(e.fixture)}</span>
                <span className="text-slate-500">{e.incident === 'repairing' ? 'repairing…' : e.status === 'restored' ? 'isolated / re-routed, waiting for the fault to clear' : e.status}</span>
                <RecoveryText e={e} className="ml-auto" />
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

// Expected recovery of a still-open incident: countdown to `recovery.ends_at` (server estimate), or the reason there is none.
function RecoveryText({ e, className = '' }) {
  const now = useNow(1000)
  if (e.incident === 'repaired') return <span className={`text-emerald-700 ${className}`}>recovered in {fmtT((e.outage_ms ?? 0) / 1000)}</span>
  if (!e.recovery) return <span className={`text-slate-400 ${className}`}>recovery time unknown</span>
  const left = (Date.parse(e.recovery.ends_at) - now) / 1000
  return <span className={`tabular-nums text-slate-700 ${className}`}>{left > 0 ? `recovers in ~${fmtT(left)}` : 'recovery due, waiting for the fault to clear'}</span>
}

function PhaseBar({ ev, now }) {
  const t0 = Date.parse(ev.time) - (ev.detect_ms ?? 0)
  const elapsed = Math.max(0, now - t0)
  const done = ev.status === 'restored'
  const total = done ? ev.est_complete_ms : Math.max(elapsed, (ev.reroute_ms ?? 0) + 1)
  const det = ev.detect_ms ?? 0
  const ana = ev.compute_ms ?? Math.max(0, total - det)
  const sw = Math.max(0, total - det - ana)
  const seg = [
    { name: 'Detect', ms: det, color: AMBER },
    { name: 'Analyse', ms: ana, color: '#6366f1' },
    { name: 'Switching', ms: sw, color: done ? GREEN : '#34d399' },
  ]
  // Detect and analyse are tiny next to the switching time; give them a visible minimum width.
  const w = seg.map((s) => Math.max(s.ms / total, 0.03))
  const sum = w.reduce((a, b) => a + b, 0)
  return (
    <div>
      <div className="flex h-5 overflow-hidden rounded-md bg-slate-100">
        {seg.map((s, i) => <div key={s.name} className="h-full" style={{ width: `${(w[i] / sum) * 100}%`, background: s.color, opacity: s.ms > 0 || done ? 1 : 0.3 }} title={`${s.name}: ${fmtT(s.ms / 1000)}`} />)}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600">
        {seg.map((s) => <span key={s.name} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />{s.name} <span className="font-semibold tabular-nums text-slate-800">{fmtT(s.ms / 1000)}</span></span>)}
        <span>{done ? 'Fault → restored' : 'Elapsed'} <span className="font-semibold tabular-nums text-slate-800">{fmtT((done ? total : elapsed) / 1000)}</span></span>
      </div>
    </div>
  )
}

function InsightCard({ ev, now }) {
  const e = ev.raw
  const steps = e.steps ?? []
  const imp = e.impact
  const restoredAt = e.status === 'restored' ? new Date(Date.parse(e.time) + (e.est_complete_ms - e.detect_ms)).toISOString() : null
  let pillText = 'healing'
  if (e.incident === 'repaired') pillText = 'repaired'
  else if (e.incident === 'repairing') pillText = 'repairing'
  else if (e.status === 'restored') pillText = 'awaiting repair'
  return (
    <Card title="Why, when and how long" subtitle={`${KIND_LABEL[e.kind] ?? e.problem} · ${ev.fixture}`}
      action={<div className="flex gap-1.5">{e.simulated && <Pill tone="idle">simulated fault</Pill>}<Pill tone={e.incident === 'repaired' ? 'ok' : e.incident === 'repairing' ? 'info' : 'warn'}>{pillText}</Pill></div>}>
      <div className="space-y-4 text-sm text-slate-700">
        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[70px_1fr]">
          <dt className="text-slate-500">Why</dt><dd>{e.why}</dd>
          {e.decision && <><dt className="text-slate-500">Action</dt><dd>{e.decision}</dd></>}
          <dt className="text-slate-500">Recovery</dt>
          <dd><RecoveryText e={e} />{e.recovery && e.incident !== 'repaired' && <span className="text-xs text-slate-500"> · expected total {fmtT(e.recovery.expected_s)} from the fault · basis: {e.recovery.basis}</span>}</dd>
          <dt className="text-slate-500">When</dt>
          <dd className="tabular-nums">fault at <b>{clock(e.time)}</b>{restoredAt && <> · restored at <b>{clock(restoredAt)}</b></>}{e.repaired_at && <> · repaired at <b>{clock(e.repaired_at)}</b></>}</dd>
        </dl>
        <div>
          <div className="mb-1.5 text-xs font-medium text-slate-500">How long</div>
          <PhaseBar ev={e} now={now} />
          {steps.length > 0 && <p className="mt-1.5 text-xs text-slate-500">{steps.length} switch operation(s), one every ~0.5 s (assumed switch time). Detection and analysis are measured.</p>}
          {e.outage_ms != null && <p className="mt-1 text-xs text-slate-600">Fault to repair: <b className="tabular-nums">{fmtT(e.outage_ms / 1000)}</b> (repair switching took {fmtT(e.repaired_ms / 1000)}).</p>}
        </div>
        {imp?.after && (
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl bg-emerald-50 p-3"><div className="text-xs text-emerald-700">Re-routed / kept supplied</div><div className="text-lg font-semibold tabular-nums text-emerald-800">{kw(imp.moved_kw)}</div></div>
            <div className="rounded-xl bg-amber-50 p-3"><div className="text-xs text-amber-700">Curtailed / left unserved</div><div className="text-lg font-semibold tabular-nums text-amber-800">{kw(imp.unserved_kw)}</div></div>
            <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
              {LIVE_BUSES.filter((b) => imp.before[b] && imp.after[b]).map((b) => <div key={b} className="tabular-nums"><b>{nodeLabel(b)}</b>: {kw(imp.before[b].load_kw)} → {kw(imp.after[b].load_kw)} <span className="text-slate-400">(limit {kw(imp.after[b].capacity_kw)})</span></div>)}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

function Insights({ events }) {
  const done = events.filter((e) => e.raw.status === 'restored' && e.raw.kind && e.raw.est_complete_ms != null)
  if (!done.length) return null
  const by = (k) => done.filter((e) => e.raw.kind === k)
  const rows = Object.keys(KIND_LABEL).map((k) => ({ k, n: by(k).length, avg: avg(by(k).map((e) => e.raw.est_complete_ms / 1000)) })).filter((r) => r.n)
  const longest = done.reduce((m, e) => (e.raw.est_complete_ms > m.raw.est_complete_ms ? e : m))
  return (
    <Card title="Healing insights" subtitle="Across the live events since the backend started.">
      <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
        {rows.map((r) => <div key={r.k} className="rounded-xl border border-slate-200 p-3"><div className="text-xs text-slate-500">{KIND_LABEL[r.k]}</div><div className="text-lg font-semibold tabular-nums">{r.n}× <span className="text-sm font-normal text-slate-500">avg {fmtT(r.avg)}</span></div></div>)}
        <div className="rounded-xl border border-slate-200 p-3"><div className="text-xs text-slate-500">Load re-routed (total)</div><div className="text-lg font-semibold tabular-nums">{kw(done.reduce((a, e) => a + (e.raw.impact?.moved_kw ?? 0), 0))}</div></div>
        <div className="rounded-xl border border-slate-200 p-3"><div className="text-xs text-slate-500">Longest restoration</div><div className="text-lg font-semibold tabular-nums">{fmtT(longest.raw.est_complete_ms / 1000)}</div><div className="text-xs text-slate-400">{KIND_LABEL[longest.raw.kind]} · {longest.fixture}</div></div>
      </div>
    </Card>
  )
}

// Who was moved where, derived from the event's path: opened feeder -> closed tie. `to: null` = just disconnected.
const isBusId = (id) => String(id).startsWith('bus_')
function routesOf(e) {
  const p = e.path
  if (!p) return []
  const iso = p.isolated_lines ?? []
  const lines = p.lines ?? []
  if (e.kind === 'node_fault') return iso.map(([a, b]) => ({ name: a, from: b, to: null }))
  const uplink = iso.find(([a, b]) => isBusId(a) && b === 'grid')
  const out = []
  for (const [a, b] of lines) {
    if (isBusId(a) || a === 'grid' || !isBusId(b)) continue
    const home = iso.find(([x]) => x === a)?.[1] ?? uplink?.[0]
    if (home && home !== b) out.push({ name: a, from: home, to: b })
  }
  for (const [a, b] of iso) if (!isBusId(a) && a !== 'grid' && !out.some((o) => o.name === a)) out.push({ name: a, from: b, to: null })
  return out
}

function incidentTitle(e) {
  if (e.kind === 'node_fault') return `${nodeLabel(e.fixture)} is faulty`
  if (e.kind === 'line_fault') return `Line ${lineName(e.fixture)} is faulty`
  const b = e.impact?.before?.[e.fixture]
  return `${nodeLabel(e.fixture)} is overloaded${b ? ` (${kw(b.load_kw)} of ${kw(b.capacity_kw)})` : ''}`
}

function IncidentCard({ e }) {
  const routes = routesOf(e)
  const open = e.incident !== 'repaired'
  const unserved = e.impact?.unserved_kw
  return (
    <div className={`rounded-xl border p-3 ${open ? 'border-red-200 bg-red-50/40' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={open ? 'bad' : 'ok'}>{open ? (e.incident === 'repairing' ? 'Repairing' : 'Active') : 'Repaired'}</Pill>
        <span className="text-sm font-semibold text-slate-900">{incidentTitle(e)}</span>
        <span className="ml-auto text-xs text-slate-500">{clock(e.time)}</span>
      </div>
      <div className="mt-2 space-y-1.5">
        {routes.length === 0 && <p className="text-xs text-slate-600">{e.decision ?? 'Working on it…'}</p>}
        {routes.map((r) => (
          <div key={r.name} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-md bg-white px-2 py-0.5 font-medium shadow-sm ring-1 ring-slate-200">{nodeLabel(r.name)}</span>
            <span className="text-slate-500">{nodeLabel(r.from)}</span>
            <span className="text-slate-400">→</span>
            {r.to ? <span className="rounded-md bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-800">rerouted to {nodeLabel(r.to)}</span>
              : <span className="rounded-md bg-slate-200 px-2 py-0.5 font-semibold text-slate-700">disconnected (isolated)</span>}
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 text-xs text-slate-500">
        {unserved > 0.5 && <span>{kw(unserved)} not served</span>}
        {open ? <RecoveryText e={e} /> : <span className="text-emerald-700">back to normal after {fmtT((e.outage_ms ?? 0) / 1000)}</span>}
      </div>
    </div>
  )
}

function Summary({ events }) {
  const list = events.filter((e) => e.kind).slice().reverse()
  const open = list.filter((e) => e.incident !== 'repaired')
  const recent = list.filter((e) => e.incident === 'repaired').slice(0, 3)
  return (
    <Card title="Faults and rerouting" subtitle={open.length ? `${open.length} active problem(s)` : 'Everything is normal'}>
      {list.length === 0 ? <EmptyState icon="check">No faulty node or line, and no overloaded bus.</EmptyState> : (
        <div className="space-y-2">
          {open.map((e) => <IncidentCard key={e.id} e={e} />)}
          {open.length === 0 && <p className="text-sm text-emerald-700">No active problem. Latest repaired incidents:</p>}
          {recent.map((e) => <IncidentCard key={e.id} e={e} />)}
        </div>
      )}
    </Card>
  )
}

function LiveView({ onConnected }) {
  const { nodes, healingEvents, connected } = useDigitalTwinSocket()
  useEffect(() => onConnected(connected), [connected, onConnected])
  const events = useMemo(() => healingEvents.map(normLive), [healingEvents])
  const [sel, setSel] = useState(null)
  useEffect(() => setSel(null), [events.length]) // a new incident takes over the map; clicking a row pins an older one
  const cur = events.find((e) => e.id === sel) ?? events[events.length - 1]
  const { nodes: gn, edges: ge } = useMemo(() => liveGraph(nodes, cur?.raw), [nodes, cur])
  return (
    <div className="space-y-5">
      <Summary events={healingEvents} />
      <Card title="Bus loads" subtitle="Load against limit for each bus.">
        <BusMeters nodes={nodes} />
      </Card>
      <Card title="Grid map" subtitle="Red = faulty node or line, grey = isolated, green = new path, dashed grey = unused tie switch.">
        <Canvas nodes={gn} edges={ge} label="Live node twin" />
        <div className="mt-3"><Legend /></div>
      </Card>
      <details className="rounded-2xl border border-slate-200 bg-white p-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-700">Technical details (switch steps, timings, event log)</summary>
        <div className="mt-4">
          <Body events={events} sel={cur?.id} onSelect={setSel} live insights={<Insights events={events} />} empty="No events yet." />
        </div>
      </details>
    </div>
  )
}

// ---------- replayed A / B / C ----------

function deriveSim(top, sc) {
  const tw = sc.twin
  if (!tw.detected) return null
  const stages = tw.stages
  const st0 = stages[0]
  const act = stages.find((s) => s.name.startsWith('Action applied'))
  const fin = act ?? stages[stages.length - 1]
  const label = (i) => top.nodes[i]?.label ?? i
  const faultLineIds = st0.highlight_lines ?? []
  const fixture = sc.fault_nodes?.length ? `Node ${sc.fault_nodes.map(label).join(', ')}` : faultLineIds.length ? faultLineIds.map((i) => `Line L${top.lines[i].paper_no}`).join(', ') : '—'
  const deadBefore = new Set(st0.energised.map((v, i) => (v ? -1 : i)).filter((i) => i >= 0))
  const deadAfter = new Set(fin.energised.map((v, i) => (v ? -1 : i)).filter((i) => i >= 0))
  // A bus still unsupplied after the recorded action is re-fed: close an open (non-faulted) line / tie that
  // links it to a supplied bus, repeating until nothing more can be reached. Display-side only.
  const status = fin.status.map(Boolean)
  const extraCloses = []
  const reFed = new Set()
  for (let moved = true; moved;) {
    moved = false
    for (const l of top.lines) {
      if (status[l.id] || faultLineIds.includes(l.id)) continue
      const aDead = deadAfter.has(l.a), bDead = deadAfter.has(l.b)
      if (aDead === bDead) continue
      const dead = aDead ? l.a : l.b
      if (sc.fault_nodes?.includes(dead)) continue
      status[l.id] = true; extraCloses.push(l.id); reFed.add(dead); deadAfter.delete(dead); moved = true
    }
  }
  const restored = [...new Set([...deadBefore, ...reFed])].filter((i) => !deadAfter.has(i))
  // BFS from the grid over lines closed after the action -> new path to each restored bus.
  const grids = top.nodes.filter((n) => n.kind === 'grid').map((n) => n.id)
  const adj = {}
  top.lines.forEach((l) => { if (status[l.id]) { (adj[l.a] ??= []).push([l.b, l.id]); (adj[l.b] ??= []).push([l.a, l.id]) } })
  const parent = new Map(grids.map((g) => [g, null]))
  const queue = [...grids]
  while (queue.length) {
    const u = queue.shift()
    for (const [v, lid] of adj[u] ?? []) if (!parent.has(v)) { parent.set(v, [u, lid]); queue.push(v) }
  }
  const pathLines = new Set()
  const unreached = []
  for (const r of restored) {
    if (!parent.has(r)) { unreached.push(r); continue }
    for (let c = r; parent.get(c); c = parent.get(c)[0]) pathLines.add(parent.get(c)[1])
  }
  const ties = top.lines.filter((l) => l.tie && status[l.id] && !st0.status[l.id]).map((l) => `L${l.paper_no}`)
  let pathText = '—'
  if (restored.length && pathLines.size) pathText = `${grids.map(label).join('/')} → ${restored.map(label).join(', ')} via ${[...pathLines].map((i) => `L${top.lines[i].paper_no}`).join(', ')}${ties.length ? ` (tie ${ties.join(', ')} closed)` : ''}`
  else if (restored.length) pathText = `Island: local sources → ${restored.map(label).join(', ')} (open + island)`
  else if (act) pathText = 'No alternative path (fault section opened)'
  const switchOps = top.lines.flatMap((l) => {
    const was = !!st0.status[l.id], now = status[l.id]
    if (was === now) return []
    return [{ op: now ? 'CLOSE' : 'OPEN', text: `${now ? 'Close' : 'Open'} ${l.tie ? 'tie switch' : 'switch on line'} L${l.paper_no} (${label(l.a)}–${label(l.b)})` }]
  }).sort((x, y) => (x.op === y.op ? 0 : x.op === 'OPEN' ? -1 : 1)) // isolate first, then close ties
  const applied = act?.t_s ?? null
  const detect = tw.detect_delay_s
  const done = act ? (tw.t_rec_s ?? applied) : null
  return {
    id: `${sc.id}`, problem: FAULT_TYPES[sc.type] ?? sc.title, fixture, detect_s: detect, reroute_s: applied, est_s: done, pathText,
    action: tw.action, switchOps, fin, st0, faultLineIds, faultNodes: sc.fault_nodes ?? [], restored, pathLines, deadBefore, deadAfter,
    openedLines: top.lines.filter((l) => !l.tie && !status[l.id]).map((l) => l.id),
  }
}

function simStatus(d, t) {
  if (t < d.detect_s) return null
  if (d.est_s == null) return 'detected'
  if (t >= d.est_s) return 'restored'
  return t < d.detect_s + (d.reroute_s - d.detect_s) * 0.3 ? 'detected' : 'rerouting'
}

function simGraph(top, d, status) {
  if (!d) return { nodes: [], edges: [] }
  const showAfter = status === 'rerouting' || status === 'restored'
  const dead = showAfter && status === 'restored' ? d.deadAfter : d.deadBefore
  const pathNodes = new Set()
  if (showAfter) d.pathLines.forEach((i) => { pathNodes.add(top.lines[i].a); pathNodes.add(top.lines[i].b) })
  const nodes = top.nodes.map((n) => ({
    id: String(n.id), type: 'heal', draggable: false, position: { x: n.x, y: n.y },
    data: { type: n.kind, label: n.label, fault: d.faultNodes.includes(n.id), grey: dead.has(n.id), onPath: pathNodes.has(n.id) },
  }))
  const edges = top.lines.map((l) => {
    const id = `e${l.id}`, s = String(l.a), t = String(l.b)
    if (d.faultLineIds.includes(l.id)) return edge(id, s, t, { color: RED, width: 3.5, dashed: status === 'restored', label: `L${l.paper_no} fault` })
    if (showAfter && d.pathLines.has(l.id)) return edge(id, s, t, { color: GREEN, width: 3.5, animated: true, label: l.tie ? `tie L${l.paper_no}` : undefined })
    const open = status === 'restored' ? d.openedLines.includes(l.id) : false
    if (l.tie) return edge(id, s, t, { color: '#cbd5e1', dashed: true, width: 1 })
    return open || dead.has(l.a) && dead.has(l.b) ? edge(id, s, t, { color: GREY, dashed: true }) : edge(id, s, t)
  })
  return { nodes, edges }
}

function SimView({ name, onConnected }) {
  useEffect(() => onConnected(null), [onConnected])
  const topo = useTestbed('/testbed/topologies')
  const list = useTestbed(`/testbed/topologies/${name}/faults`)
  const [scen, setScen] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    setScen(null); setErr(null)
    if (!list.data) return undefined
    let alive = true
    Promise.all(list.data.scenarios.map((s) => apiFetch(`/testbed/topologies/${name}/faults/${s.id}`).then((r) => r.json())))
      .then((all) => alive && setScen(all))
      .catch((e) => alive && setErr(String(e)))
    return () => { alive = false }
  }, [list.data, name])

  const top = topo.data?.topologies?.[name]
  const derived = useMemo(() => {
    if (!top || !scen) return null
    const ds = scen.map((s) => deriveSim(top, s)).filter(Boolean)
    let at = 0
    return ds.map((d) => { const start = at; at += (d.est_s ?? d.detect_s + 30) + GAP_S; return { ...d, start } })
  }, [top, scen])
  const total = derived?.length ? derived[derived.length - 1].start + (derived[derived.length - 1].est_s ?? 60) + GAP_S : 0

  const [simT, setSimT] = useState(0)
  const [run, setRun] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [sel, setSel] = useState(null)
  const [prev, setPrev] = useState(null) // click-to-play reroute: {id, p} with p in 0..1
  const playingRef = useRef(playing)
  playingRef.current = playing
  useEffect(() => { setSimT(0); setSel(null) }, [name, run])
  useEffect(() => {
    const id = setInterval(() => playingRef.current && setSimT((t) => (t >= total ? t : t + (TICK_MS / 1000) * SIM_SPEED)), TICK_MS)
    return () => clearInterval(id)
  }, [total])

  useEffect(() => {
    if (!prev || prev.p >= 1) return undefined
    const id = setTimeout(() => setPrev((x) => (x ? { ...x, p: Math.min(1, x.p + 0.04) } : x)), 100)
    return () => clearTimeout(id)
  }, [prev])

  if (topo.loading || list.loading || (!scen && !err && !list.error)) return <Loading what="fault scenarios" />
  if (topo.error || list.error || err) return <ErrorNote error={topo.error ?? list.error ?? err} />
  const rows = (derived ?? []).map((d) => ({ d, t: simT - d.start })).filter(({ d, t }) => simStatus(d, t))
  const events = rows.map(({ d, t }) => {
    const status = simStatus(d, t)
    const playing = prev && prev.id === d.id && prev.p < 1
    const shown = playing ? Math.ceil(prev.p * d.switchOps.length) : status === 'detected' ? 0 : d.switchOps.length
    const gstatus = playing ? (prev.p < 0.25 ? 'detected' : prev.p < 0.75 ? 'rerouting' : 'restored') : status
    return { id: d.id, problem: d.problem, fixture: d.fixture, status, gstatus, detect_s: d.detect_s, reroute_s: status === 'detected' ? null : d.reroute_s, est_s: d.est_s, remaining_s: d.est_s == null ? null : Math.max(0, d.est_s - t), restore_s: status === 'restored' ? d.est_s : null, pathText: d.pathText, action: d.action, switchOps: d.switchOps, shown, d }
  })
  const cur = events.find((e) => e.id === sel) ?? events[events.length - 1]
  const { nodes: gn, edges: ge } = simGraph(top, cur?.d, cur?.gstatus ?? cur?.status)
  const skipped = (scen?.length ?? 0) - (derived?.length ?? 0)
  return (
    <Body
      events={events} sel={cur?.id} onSelect={(id) => { setSel(id); setPrev({ id, p: 0 }) }}
      canvas={<Canvas nodes={gn} edges={ge} label={top.title} />}
      empty="Replay starting…"
      note={`Saved fault scenarios of ${top.title} replayed at ${SIM_SPEED}x. Times are in seconds (t = 0 at the fault). ${skipped > 0 ? `${skipped} saved scenario(s) were never detected, so they trigger no healing and are not listed.` : ''}`}
      controls={
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Play'}</Button>
          <Button variant="secondary" onClick={() => { setRun((r) => r + 1); setPlaying(true) }}>Replay</Button>
        </div>
      }
    />
  )
}

// ---------- shared body: summary + graph + table ----------

function Body({ events, sel, onSelect, canvas, empty, note, controls, live, top, insights }) {
  const now = useNow(250)
  const det = events.map((e) => e.detect_s).filter((v) => v != null)
  const res = events.map((e) => e.restore_s).filter((v) => v != null)
  return (
    <div className="space-y-5">
      {top}
      {canvas && <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Total events" value={String(events.length)} hint={`${events.filter((e) => e.status === 'restored').length} restored`} />
        <StatCard label="Avg detection time" value={fmtT(avg(det)).split(' ')[0]} unit={fmtT(avg(det)).split(' ')[1] ?? ''} hint="fault → detected" />
        <StatCard label="Avg restoration time" value={fmtT(avg(res)).split(' ')[0]} unit={fmtT(avg(res)).split(' ')[1] ?? ''} hint="fault → restored" />
      </div>}
      {canvas && <Card title="Topology" subtitle={note} action={controls}>
        {canvas}
        <div className="mt-3"><Legend /></div>
      </Card>}
      {(() => {
        const ev = events.find((e) => e.id === sel)
        if (!ev) return null
        const ops = ev.switchOps ?? []
        const shown = ev.shown ?? (ev.status === 'detected' ? 0 : ops.length)
        const eta = ev.raw && ev.status !== 'restored' ? `healing… ${fmtT(Math.max(0, now - Date.parse(ev.raw.time) + (ev.raw.detect_ms ?? 0)) / 1000)} elapsed` : ev.raw?.est_complete_ms && ev.status === 'restored' ? `Restored in ${fmtT(ev.raw.est_complete_ms / 1000)}` : ev.status === 'restored' ? 'Restored' : ev.est_s == null ? 'Estimating…' : ev.remaining_s != null ? `~${fmtT(ev.remaining_s)} remaining (total ${fmtT(ev.est_s)})` : `~${fmtT(ev.est_s)}`
        return (<>
          <Card title="Switch actions & estimated healing" subtitle={`${ev.problem} · ${ev.fixture}`} action={<Pill tone={STATUS_TONE[ev.status]}>{ev.status}</Pill>}>
            <div className="mb-3 text-sm text-slate-700">Estimated time to heal: <span className="font-semibold tabular-nums">{eta}</span></div>
            {ops.length === 0 ? <p className="text-xs text-slate-500">No switch operation needed for this event.</p> : (
              <ol className="space-y-1.5 text-xs">
                {ops.map((o, i) => (
                  <li key={i} className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 ${i < shown ? 'border-emerald-200 bg-emerald-50 text-slate-800' : 'border-slate-200 text-slate-400'}`}>
                    <span className="w-4 tabular-nums">{i + 1}.</span>
                    <span className={`rounded px-1.5 py-0.5 font-semibold ${OP_TONE[o.op] ?? OP_TONE.CLOSE}`}>{o.op}</span>
                    <span>{o.text}</span>
                    <span className="ml-auto">{i < shown ? 'done' : 'pending'}</span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          {ev.raw?.why && <InsightCard ev={ev} now={now} />}
        </>)
      })()}
      {insights}
      <Card title="Self-healing events" subtitle={live ? 'Newest last. Click a row to show it on the graph.' : 'Click a row to play its rerouting on the graph and list its switch actions.'}>
        {events.length === 0 ? <EmptyState>{empty}</EmptyState> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-xs">
              <thead>
                <tr className="text-slate-400">
                  <th className="py-1.5 pr-3">Problem</th><th className="pr-3">Fixture</th><th className="pr-3">Detect</th><th className="pr-3">Evaluated rerouting time</th>
                  <th className="pr-3">Rerouting path</th><th className="pr-3">Est. completion</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} onClick={() => onSelect(e.id)} className={`cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50 ${e.id === sel ? 'bg-indigo-50' : ''}`}>
                    <td className="py-1.5 pr-3 font-medium text-slate-800">{e.problem}</td>
                    <td className="pr-3">{e.fixture}</td>
                    <td className="pr-3 tabular-nums">{fmtT(e.detect_s)}</td>
                    <td className="pr-3 tabular-nums">{fmtT(e.reroute_s)}</td>
                    <td className="pr-3 text-slate-600">{e.pathText}{e.action ? <span className="text-slate-400"> · {String(e.action).replace(/_/g, ' ')}</span> : null}</td>
                    <td className="pr-3 tabular-nums">{fmtT(e.est_s)}</td>
                    <td><Pill tone={STATUS_TONE[e.status]}>{e.status}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

export default function SelfHealingTab() {
  const [name, setName] = useState('live')
  const [connected, setConnected] = useState(null)
  useReportConnection(connected)
  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <Segmented options={TOPS} value={name} onChange={setName} />
      {name === 'live' ? <LiveView key="live" onConnected={setConnected} /> : <SimView key={name} name={name} onConnected={setConnected} />}
    </div>
  )
}
