import { useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, Handle, Position, ReactFlow } from '@xyflow/react'
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
//  - Live 9-node twin (incl. solar_01 and the solar hardware node): events come from the backend
//    (app/twin/healing_events.py) over the existing /ws/updates socket via useDigitalTwinSocket.
//  - A radial / B meshed / C IEEE 33-bus: no live stream exists for these (they are saved simulation
//    results), so the saved fault scenarios (/testbed/topologies/{A,B,C}/faults) are replayed in real time
//    (SIM_SPEED seconds per real second).
// Overlay: red = faulted element, grey = isolated section, animated green = new path.

const TOPS = [
  { id: 'live', label: 'Live 9-node' },
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
  const ring = data.fault ? RED : data.grey ? GREY : data.onPath ? GREEN : '#e2e8f0'
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

function Canvas({ nodes, edges, label }) {
  return (
    <div className="h-[520px] rounded-xl border border-slate-200 bg-slate-50" role="img" aria-label={label}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12 }} nodesConnectable={false} nodesDraggable={false} proOptions={{ hideAttribution: true }} minZoom={0.2}>
        <Background color="#e2e8f0" gap={24} />
        <Controls showInteractive={false} />
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

const LIVE_POS = {
  wind_01: [0, 0], hydro_01: [0, 90], wind_scada_kelmarsh_1: [0, 180], wind_scada_kelmarsh_2: [0, 270], wind_scada_kelmarsh_3: [0, 360], wind_scada_kelmarsh_4: [0, 450],
  solar_01: [0, 540], solar_hardware: [0, 630], bus_a: [330, 170], bus_b: [330, 430], grid: [620, 300],
}

function liveGraph(twinNodes, ev) {
  const path = ev?.path
  const pathNodes = new Set(path ? path.lines.flat() : [])
  const nodes = Object.values(twinNodes)
    .filter((n) => LIVE_POS[n.node_id])
    .map((n) => ({
      id: n.node_id, type: 'heal', draggable: false,
      position: { x: LIVE_POS[n.node_id][0], y: LIVE_POS[n.node_id][1] },
      data: {
        type: n.type, label: nodeLabel(n.node_id), sub: n.node_id === 'solar_hardware' ? 'ESP32 sensed' : n.type === 'bus' || n.type === 'grid' ? undefined : n.source_type === 'live' ? 'Live' : 'Replayed',
        fault: ev?.fixture === n.node_id && ev.status !== 'restored' ? true : ev?.fixture === n.node_id && ev.action === 'isolate',
        grey: n.isolated || (ev?.action === 'isolate' && ev.fixture === n.node_id),
        onPath: pathNodes.has(n.node_id) && n.node_id !== ev?.fixture,
      },
    }))
  const pathKeys = new Set((path?.lines ?? []).map(([a, b]) => `${a}>${b}`))
  const edges = []
  for (const n of Object.values(twinNodes)) {
    if (!LIVE_POS[n.node_id] || n.type === 'bus' && n.node_id !== 'bus_a' && n.node_id !== 'bus_b') continue
    const target = n.type === 'bus' ? 'grid' : n.active_connection
    if (!target || n.type === 'grid') continue
    const onPath = pathKeys.has(`${n.node_id}>${target}`)
    edges.push(edge(`${n.node_id}>${target}`, n.node_id, target, onPath ? { color: GREEN, width: 3.5, animated: true } : {}))
  }
  for (const [a, b] of path?.lines ?? []) { // path lines that are not current twin edges (e.g. bus -> grid already covered)
    if (!edges.some((e) => e.id === `${a}>${b}`)) edges.push(edge(`${a}>${b}`, a, b, { color: GREEN, width: 3.5, animated: true }))
  }
  for (const [a, b] of path?.isolated_lines ?? []) edges.push(edge(`iso-${a}>${b}`, a, b, { color: RED, dashed: true, width: 2, label: 'opened' }))
  return { nodes, edges }
}

function normLive(e) {
  const p = e.path
  const pathText = !p ? '—' : p.to ? `${nodeLabel(p.from)} → ${nodeLabel(p.via)} → ${nodeLabel(p.to)} (${p.lines.map(([a, b]) => `${nodeLabel(a)}–${nodeLabel(b)}`).join(', ')})` : `${nodeLabel(p.from)} isolated (no path)`
  return {
    id: e.id, problem: e.problem, fixture: nodeLabel(e.fixture), status: e.status,
    detect_s: e.detect_ms == null ? null : e.detect_ms / 1000,
    reroute_s: e.reroute_ms == null ? null : e.reroute_ms / 1000,
    est_s: e.est_complete_ms == null ? null : e.est_complete_ms / 1000,
    restore_s: e.status === 'restored' ? e.est_complete_ms / 1000 : null,
    pathText, action: e.action, raw: e,
    switchOps: [
      ...(p?.isolated_lines ?? []).map(([a, b]) => ({ op: 'OPEN', text: `Open switch ${nodeLabel(a)}–${nodeLabel(b)} (isolate fault)` })),
      ...(p?.to ? p.lines.map(([a, b]) => ({ op: 'CLOSE', text: `Close / route ${nodeLabel(a)}–${nodeLabel(b)}` })) : []),
    ],
  }
}

function LiveView({ onConnected }) {
  const { nodes, healingEvents, connected } = useDigitalTwinSocket()
  useEffect(() => onConnected(connected), [connected, onConnected])
  const events = useMemo(() => healingEvents.map(normLive), [healingEvents])
  const [sel, setSel] = useState(null)
  const cur = events.find((e) => e.id === sel) ?? events[events.length - 1]
  const { nodes: gn, edges: ge } = useMemo(() => liveGraph(nodes, cur?.raw), [nodes, cur])
  return (
    <Body
      events={events} sel={cur?.id} onSelect={setSel} live
      canvas={<Canvas nodes={gn} edges={ge} label="Live 9-node twin" />}
      empty="No self-healing event yet. Events appear here the moment the twin reacts to a fault (the replayed Kelmarsh turbines trigger them)."
      note="Live from the Digital Twin (/ws/updates). Detection and compute times are measured; completion time adds an assumed 0.5 s per switch operation."
    />
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

function Body({ events, sel, onSelect, canvas, empty, note, controls, live }) {
  const det = events.map((e) => e.detect_s).filter((v) => v != null)
  const res = events.map((e) => e.restore_s).filter((v) => v != null)
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Total events" value={String(events.length)} hint={`${events.filter((e) => e.status === 'restored').length} restored`} />
        <StatCard label="Avg detection time" value={fmtT(avg(det)).split(' ')[0]} unit={fmtT(avg(det)).split(' ')[1] ?? ''} hint="fault → detected" />
        <StatCard label="Avg restoration time" value={fmtT(avg(res)).split(' ')[0]} unit={fmtT(avg(res)).split(' ')[1] ?? ''} hint="fault → restored" />
      </div>
      <Card title="Topology" subtitle={note} action={controls}>
        {canvas}
        <div className="mt-3"><Legend /></div>
      </Card>
      {(() => {
        const ev = events.find((e) => e.id === sel)
        if (!ev) return null
        const ops = ev.switchOps ?? []
        const shown = ev.shown ?? (ev.status === 'detected' ? 0 : ops.length)
        const eta = ev.status === 'restored' ? 'Restored' : ev.est_s == null ? 'Estimating…' : ev.remaining_s != null ? `~${fmtT(ev.remaining_s)} remaining (total ${fmtT(ev.est_s)})` : `~${fmtT(ev.est_s)}`
        return (
          <Card title="Switch actions & estimated healing" subtitle={`${ev.problem} · ${ev.fixture}`} action={<Pill tone={STATUS_TONE[ev.status]}>{ev.status}</Pill>}>
            <div className="mb-3 text-sm text-slate-700">Estimated time to heal: <span className="font-semibold tabular-nums">{eta}</span></div>
            {ops.length === 0 ? <p className="text-xs text-slate-500">No switch operation needed for this event.</p> : (
              <ol className="space-y-1.5 text-xs">
                {ops.map((o, i) => (
                  <li key={i} className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 ${i < shown ? 'border-emerald-200 bg-emerald-50 text-slate-800' : 'border-slate-200 text-slate-400'}`}>
                    <span className="w-4 tabular-nums">{i + 1}.</span>
                    <span className={`rounded px-1.5 py-0.5 font-semibold ${o.op === 'OPEN' ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>{o.op}</span>
                    <span>{o.text}</span>
                    <span className="ml-auto">{i < shown ? 'done' : 'pending'}</span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        )
      })()}
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
