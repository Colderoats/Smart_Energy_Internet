import { useEffect, useMemo, useState } from 'react'
import { Background, Controls, Handle, Position, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import FlowEdge, { flowWidth } from '../components/FlowEdge'
import { SourceIcon } from '../ui/icons'
import { Button, Card, Details, EmptyState, Pill, Segmented, StatCard } from '../ui/components'
import { SOURCE_COLORS, STATUS_COLORS } from '../ui/theme'
import { ErrorNote, Loading, SimPill } from '../testbed/common'
import { fmt } from '../testbed/format'
import { useTestbed } from '../testbed/useTestbed'

// Topologies: A radial / B meshed / C IEEE 33-bus as React Flow graphs (existing node-card + FlowEdge style),
// redistribution playback (flows from the saved trading day), fault replay (saved twin evaluation) and per-topology KPIs.
// Everything is read from /testbed/* (saved simulation results). No value is computed in the browser except the
// plain-language sentences, which only quote measured numbers shown on the same page.

const TOPS = [
  { id: 'A', label: 'A Radial' },
  { id: 'B', label: 'B Meshed' },
  { id: 'C', label: 'C IEEE 33-bus' },
]
const KIND_COLOR = { solar: SOURCE_COLORS.solar, wind: SOURCE_COLORS.wind, hydro: SOURCE_COLORS.hydro, grid: SOURCE_COLORS.grid, load: '#64748b', collector: '#94a3b8' }
const KIND_ICON = { solar: 'solar', wind: 'wind', hydro: 'hydro', grid: 'grid', load: 'bus', collector: 'bus' }
const KIND_LABEL = { solar: 'Solar', wind: 'Wind', hydro: 'Hydro', grid: 'Grid / slack', load: 'Load bus', collector: 'Collector bus' }

function BusNode({ data }) {
  const color = KIND_COLOR[data.kind] ?? '#64748b'
  const ring = data.dead ? STATUS_COLORS.bad : data.faulty ? STATUS_COLORS.warn : '#e2e8f0'
  return (
    <div className="min-w-[96px] rounded-xl border-2 bg-white px-2 py-1.5 text-slate-800 shadow-sm" style={{ borderColor: ring, opacity: data.dead ? 0.55 : 1 }} title={data.title}>
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <div className="flex items-center gap-1.5">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg" style={{ background: `${color}1f`, color }}>
          <SourceIcon type={KIND_ICON[data.kind]} size={14} />
        </span>
        <div className="leading-tight">
          <div className="text-[11px] font-semibold">{data.label}</div>
          <div className="text-[10px] text-slate-500">{data.sub}</div>
        </div>
      </div>
      {data.soc != null && (
        <div className="mt-1" title={`State of charge ${(data.soc * 100).toFixed(0)} %`}>
          <div className="h-1 w-full overflow-hidden rounded bg-slate-200"><div className="h-1 rounded bg-violet-500" style={{ width: `${Math.round(data.soc * 100)}%` }} /></div>
          <div className="text-[9px] text-slate-400">storage SOC {(data.soc * 100).toFixed(0)} %</div>
        </div>
      )}
    </div>
  )
}

function TieEdge({ sourceX, sourceY, targetX, targetY, data = {} }) {
  const open = !data.closed
  return (
    <g>
      <line x1={sourceX} y1={sourceY} x2={targetX} y2={targetY} stroke={open ? '#cbd5e1' : '#6366f1'} strokeWidth={open ? 1.5 : 3} strokeDasharray={open ? '6 5' : undefined} />
      <text x={(sourceX + targetX) / 2} y={(sourceY + targetY) / 2 - 4} fontSize={9} textAnchor="middle" fill={open ? '#94a3b8' : '#4338ca'}>
        {open ? `tie ${data.no} (open)` : `tie ${data.no} (closed)`}
      </text>
    </g>
  )
}

const nodeTypes = { bus: BusNode }
const edgeTypes = { flow: FlowEdge, tie: TieEdge }

function buildGraph(top, { frame, status, energised, highlight, faultNodes }) {
  const maxKw = frame ? Math.max(1, ...frame.line_p_kw.map((v) => Math.abs(v))) : 1
  const nodes = top.nodes.map((n) => {
    const inj = frame?.inj_kw?.[n.id]
    const sub = frame ? `${inj > 0 ? '+' : ''}${fmt(inj ?? 0, '', 0)} kW` : n.gen_cap_kw ? `${n.gen_cap_kw} kW cap` : n.load_kw ? `${Math.round(n.load_kw)} kW load` : KIND_LABEL[n.kind]
    return {
      id: String(n.id),
      type: 'bus',
      position: { x: n.x, y: n.y },
      draggable: false,
      data: {
        kind: n.kind, label: n.label, sub, soc: n.storage_kwh > 0 ? (frame?.soc?.[n.id] ?? 0.5) : null,
        dead: energised ? !energised[n.id] : false, faulty: faultNodes?.includes(n.id),
        title: `${KIND_LABEL[n.kind]}${n.load_kw ? ` · load ${Math.round(n.load_kw)} kW` : ''}${n.gen_cap_kw ? ` · generation cap ${n.gen_cap_kw} kW` : ''}${n.storage_kwh ? ` · storage ${n.storage_kwh} kWh / ${n.storage_kw} kW` : ''}`,
      },
    }
  })
  const edges = top.lines.map((l) => {
    const closed = status ? status[l.id] : !l.tie
    const p = frame?.line_p_kw?.[l.id] ?? 0
    const loss = frame?.line_loss_kw?.[l.id] ?? 0
    if (l.tie && !closed) return { id: `e${l.id}`, source: String(l.a), target: String(l.b), type: 'tie', data: { closed: false, no: l.paper_no } }
    if (l.tie) return { id: `e${l.id}`, source: String(l.a), target: String(l.b), type: 'tie', data: { closed: true, no: l.paper_no } }
    const rev = p < 0
    const flowing = closed && Math.abs(p) > 0.5
    const hl = highlight?.includes(l.id)
    return {
      id: `e${l.id}`,
      source: String(rev ? l.b : l.a),
      target: String(rev ? l.a : l.b),
      type: 'flow',
      label: closed ? (frame ? `${fmt(Math.abs(p), '', 0)} kW${loss > 0.05 ? ` · loss ${loss.toFixed(2)}` : ''}` : undefined) : `L${l.paper_no} open`,
      labelStyle: { fontSize: 9, fill: closed ? '#475569' : '#dc2626' },
      data: { width: flowing ? flowWidth(Math.abs(p), maxKw) : closed ? 2 : 1.5, flowing, color: !closed ? '#fca5a5' : hl ? '#6366f1' : '#94a3b8', dotColor: '#6366f1', duration: 2.4 - 1.6 * Math.min(1, Math.abs(p) / maxKw) },
      style: !closed ? { strokeDasharray: '4 4' } : undefined,
    }
  })
  return { nodes, edges }
}

function Canvas({ top, ...state }) {
  const { nodes, edges } = useMemo(() => buildGraph(top, state), [top, state.frame, state.status, state.energised, state.highlight, state.faultNodes]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="h-[560px] rounded-xl border border-slate-200 bg-slate-50" role="img" aria-label={`${top.title} network`}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView fitViewOptions={{ padding: 0.12 }} nodesConnectable={false} proOptions={{ hideAttribution: true }} minZoom={0.2}>
        <Background color="#e2e8f0" gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

function Legend({ top }) {
  const kinds = [...new Set(top.nodes.map((n) => n.kind))]
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
      {kinds.map((k) => (
        <span key={k} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: KIND_COLOR[k] }} />{KIND_LABEL[k]}</span>
      ))}
      <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 bg-slate-400" />closed line</span>
      <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-5 border-t-2 border-dashed border-slate-400" />open tie / switch</span>
      <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-violet-500" />storage SOC</span>
    </div>
  )
}

function Redistribution({ name, top }) {
  const { data, error, loading } = useTestbed(`/testbed/topologies/${name}/redistribution`)
  const [variant, setVariant] = useState('normal')
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(false)
  const run = data?.[variant]
  const frames = run?.frames ?? []
  useEffect(() => { setI(0); setPlaying(false) }, [name, variant])
  useEffect(() => {
    if (!playing || frames.length === 0) return undefined
    const t = setInterval(() => setI((x) => (x + 1) % frames.length), 700)
    return () => clearInterval(t)
  }, [playing, frames.length])
  if (loading) return <Loading what="redistribution" />
  if (error) return <ErrorNote error={error} />
  const frame = frames[Math.min(i, Math.max(frames.length - 1, 0))]
  const status = run?.status ?? top.lines.map((l) => !l.tie)
  const k = run?.kpi
  return (
    <Card
      title="Redistribution playback"
      subtitle="Flows between prosumer buses over the simulated day (5-minute trading intervals). Arrow width ∝ kW; losses on lines."
      action={<div className="flex items-center gap-2"><SimPill /><Segmented size="sm" options={[{ id: 'normal', label: 'Normal topology' }, { id: 'postfault', label: 'After self-healing' }]} value={variant} onChange={setVariant} /></div>}
    >
      <p className="mb-2 text-xs text-slate-500">{run?.note}</p>
      <Canvas top={top} frame={frame} status={status} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button variant="secondary" onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Play'}</Button>
        <input aria-label="time of day" type="range" min={0} max={Math.max(frames.length - 1, 0)} value={i} onChange={(e) => { setPlaying(false); setI(Number(e.target.value)) }} className="min-w-[220px] flex-1" />
        <span className="text-sm tabular-nums text-slate-600">{frame ? `${String(Math.floor(frame.hour)).padStart(2, '0')}:${String(Math.round((frame.hour % 1) * 60)).padStart(2, '0')}` : '—'} · {frame?.trades?.length ?? 0} trade(s)</span>
      </div>
      {frame?.trades?.length > 0 && (
        <p className="mt-2 text-xs text-slate-600">{frame.trades.map((t) => `${top.nodes[t.s].label} → ${top.nodes[t.b].label}: ${fmt(t.q_kw, '', 0)} kW @ ${t.price}`).join(' · ')}</p>
      )}
      {k && (
        <div className="mt-4 grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
          <StatCard label="Energy redistributed" value={fmt(k.energy_redistributed_kwh, '', 0)} unit="kWh" hint="received by buyers" />
          <StatCard label="Network losses" value={fmt(k.network_losses_kwh, '', 1)} unit="kWh" hint={`no trading: ${fmt(k.network_losses_without_trading_kwh, '', 1)}`} />
          <StatCard label="Self-sufficiency" value={fmt(k.local_self_sufficiency * 100, '', 1)} unit="%" hint={`without trading ${fmt(k.local_self_sufficiency_without_trading * 100, '', 1)} %`} />
          <StatCard label="Grid import reduction" value={fmt(k.grid_import_reduction * 100, '', 1)} unit="%" />
          <StatCard label="Trades" value={fmt(k.trades)} hint={`${fmt(k.infeasible_rejected)} infeasible rejected`} />
          <StatCard label="Gas per trade" value={fmt(k.avg_gas_per_trade_match_meter_settle, '', 0)} hint="match + meter + settle" color="#7c3aed" />
        </div>
      )}
    </Card>
  )
}

function FaultReplay({ name, top }) {
  const list = useTestbed(`/testbed/topologies/${name}/faults`)
  const [sel, setSel] = useState(null)
  const sid = sel ?? list.data?.scenarios?.[0]?.id
  const { data: sc, error, loading } = useTestbed(sid ? `/testbed/topologies/${name}/faults/${sid}` : null)
  const [step, setStep] = useState(0)
  const [scheme, setScheme] = useState('twin')
  useEffect(() => setStep(0), [sid, scheme])
  if (list.loading) return <Loading what="fault scenarios" />
  if (list.error) return <ErrorNote error={list.error} />
  const stages = sc?.[scheme]?.stages ?? []
  const st = stages[Math.min(step, Math.max(stages.length - 1, 0))]
  return (
    <Card
      title="Fault replay"
      subtitle="A recorded fault from the held-out simulation. Step through detection, the candidate actions with their cost J, the chosen action and restoration."
      action={<div className="flex items-center gap-2"><SimPill /><Segmented size="sm" options={[{ id: 'twin', label: 'Twin' }, { id: 'default', label: 'Default scheme' }]} value={scheme} onChange={setScheme} /></div>}
    >
      <div className="mb-3 flex flex-wrap gap-2">
        {list.data.scenarios.map((s) => (
          <button key={s.id} onClick={() => setSel(s.id)} className={`rounded-lg border px-3 py-1.5 text-xs font-medium ${s.id === sid ? 'border-indigo-600 bg-indigo-50 text-indigo-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>{s.title}</button>
        ))}
      </div>
      {loading && <Loading what="scenario" />}
      {error && <ErrorNote error={error} />}
      {sc && st && (
        <div className="grid gap-4 xl:grid-cols-[1fr,340px]">
          <Canvas top={top} status={st.status} energised={st.energised} highlight={st.highlight_lines} faultNodes={sc.fault_nodes} frame={null} />
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-slate-800">Step {step + 1} / {stages.length}: {st.name}</div>
              <div className="flex gap-1.5">
                <Button variant="secondary" disabled={step === 0} onClick={() => setStep(step - 1)}>Prev</Button>
                <Button disabled={step >= stages.length - 1} onClick={() => setStep(step + 1)}>Next</Button>
              </div>
            </div>
            <p className="text-sm text-slate-600">{st.description}</p>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-lg bg-slate-50 p-2"><div className="text-[11px] text-slate-500">t − t_fault</div><div className="text-sm font-semibold tabular-nums">{fmt(st.t_s, 's', 0)}</div></div>
              <div className="rounded-lg bg-slate-50 p-2"><div className="text-[11px] text-slate-500">Unserved now</div><div className="text-sm font-semibold tabular-nums">{fmt(st.unserved_kw, 'kW', 0)}</div></div>
              <div className="rounded-lg bg-slate-50 p-2"><div className="text-[11px] text-slate-500">E_uns so far</div><div className="text-sm font-semibold tabular-nums">{fmt(st.e_uns_kwh, 'kWh', 2)}</div></div>
            </div>
            {st.candidates && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Candidate actions (J = 0.6 E_uns + 0.3 V_viol + 0.1 N_sw)</div>
                <table className="w-full text-left text-xs">
                  <thead><tr className="text-slate-400"><th>Action</th><th>J</th><th>N_sw</th><th>OK</th></tr></thead>
                  <tbody>
                    {st.candidates.map((c, idx) => (
                      <tr key={idx} className={`border-t border-slate-100 ${c.chosen ? 'bg-indigo-50 font-semibold' : ''}`}>
                        <td className="py-1">{c.label}{c.chosen ? ' ← a*' : ''}</td><td className="tabular-nums">{fmt(c.J, '', 3)}</td><td>{c.n_sw}</td><td>{c.feasible ? 'feasible' : 'rejected'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <Pill tone="info" dot={false}>T_rec {sc[scheme].t_rec_s == null ? 'n/a (no interruption)' : `${fmt(sc[scheme].t_rec_s, 's', 0)}`}</Pill>
              <Pill tone="info" dot={false}>E_uns {fmt(sc[scheme].e_uns_kwh, 'kWh', 2)}</Pill>
              <Pill tone={sc[scheme].detected ? 'ok' : 'bad'}>{sc[scheme].detected ? `detected after ${fmt(sc[scheme].detect_delay_s, 's', 0)}` : 'not detected'}</Pill>
            </div>
          </div>
        </div>
      )}
      {!sid && <EmptyState>No fault scenarios recorded.</EmptyState>}
    </Card>
  )
}

function Kpis({ k }) {
  if (!k) return <EmptyState>KPIs appear once the evaluation runs have been exported.</EmptyState>
  const items = [
    ['Forecast MAE', fmt(k.forecast_mae_kw, 'kW'), 'TA-GNN, validation'],
    ['Forecast RMSE', fmt(k.forecast_rmse_kw, 'kW'), 'TA-GNN, validation'],
    ['Detection F1 (twin)', fmt(k.detection_f1_twin, '', 3), `default ${fmt(k.detection_f1_default, '', 3)}`],
    ['T_rec (twin)', fmt(k.t_rec_twin_s, 's', 1), `default ${fmt(k.t_rec_default_s, 's', 1)}`],
    ['E_uns (twin)', fmt(k.e_uns_twin_kwh, 'kWh', 1), `default ${fmt(k.e_uns_default_kwh, 'kWh', 1)}`],
    ['Energy redistributed', fmt(k.energy_redistributed_kwh, 'kWh', 0), 'one simulated day'],
    ['Self-sufficiency', fmt(k.self_sufficiency * 100, '%', 1), 'with trading'],
    ['Network losses', fmt(k.losses_kwh, 'kWh', 1), 'with trading'],
    ['Trades', fmt(k.trades), `${fmt(k.avg_gas_per_trade, 'gas', 0)} / trade (match+meter+settle)`],
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
      {items.map(([l, v, h]) => (
        <StatCard key={l} label={l} value={v.split(' ')[0]} unit={v.split(' ').slice(1).join(' ')} hint={h} />
      ))}
    </div>
  )
}

function Why({ top, k }) {
  const n1 = top.n1
  const lines = []
  lines.push(`Topology ${top.name} has ${top.counts.nodes} nodes, ${top.counts.lines} lines and ${top.counts.ties} normally-open tie switch${top.counts.ties === 1 ? '' : 'es'}.`)
  if (n1) {
    lines.push(`A single line outage leaves every bus connected to the grid in ${n1.keeps_connected} of ${n1.lines_tested} cases once the tie switches are available (${n1.keeps_connected_no_ties} of ${n1.lines_tested} without them), so ${n1.keeps_connected === 0 ? 'every outage cuts off a section and only islanding or curtailment can help' : n1.keeps_connected === n1.lines_tested ? 'every outage can in principle be bypassed by re-routing' : 'some outages can be bypassed by closing a tie, the rest need islanding'}.`)
  }
  if (k?.t_rec_default_s != null && k?.t_rec_twin_s != null) {
    const d = ((k.t_rec_default_s - k.t_rec_twin_s) / k.t_rec_default_s) * 100
    lines.push(`Measured recovery time: default ${fmt(k.t_rec_default_s, 's', 1)}, twin ${fmt(k.t_rec_twin_s, 's', 1)} (${d >= 0 ? '−' : '+'}${Math.abs(d).toFixed(1)} %). The fixed-sequence default tries tie switches in list order, the twin evaluates all candidates and applies the cheapest one directly.`)
  }
  if (k?.e_uns_default_kwh != null) lines.push(`Unserved energy over the scenario: default ${fmt(k.e_uns_default_kwh, 'kWh', 1)}, twin ${fmt(k.e_uns_twin_kwh, 'kWh', 1)}.`)
  return (
    <Card title="Why these numbers" subtitle="Each sentence quotes a number measured on this page; nothing is claimed beyond it." action={<SimPill />}>
      <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-700">{lines.map((l) => <li key={l}>{l}</li>)}</ul>
    </Card>
  )
}

export default function TopologiesTab() {
  const [name, setName] = useState('A')
  const { data, error, loading } = useTestbed('/testbed/topologies')
  if (loading) return <div className="p-6"><Loading what="topologies" /></div>
  if (error) return <div className="mx-auto max-w-7xl p-6"><ErrorNote error={error} /></div>
  const top = data.topologies[name]
  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-500">The three journal topologies of the simulated testbed. Nodes are generation, storage, load and collector buses (prosumer buses carry both generation and load); there are no households.</p>
        <Segmented options={TOPS} value={name} onChange={setName} />
      </div>
      <Card title={top.title} subtitle={`${top.counts.nodes} nodes · ${top.counts.lines} lines · ${top.counts.solar} solar · ${top.counts.wind_hydro} wind/hydro · ${top.counts.ties} tie switches · ${top.counts.storage} storage units`} action={<SimPill />}>
        <Canvas top={top} status={null} frame={null} />
        <div className="mt-3"><Legend top={top} /></div>
      </Card>
      <Redistribution key={`r${name}`} name={name} top={top} />
      <FaultReplay key={`f${name}`} name={name} top={top} />
      <Card title="Topology KPIs" subtitle="From the saved runs behind the Results tab." action={<SimPill />}><Kpis k={data.kpis?.[name]} /></Card>
      <Why top={top} k={data.kpis?.[name]} />
      <Details label="Topology description"><pre className="overflow-x-auto rounded-xl bg-slate-50 p-3 text-xs">{JSON.stringify(top.counts, null, 1)}</pre></Details>
    </div>
  )
}
