import { useEffect, useMemo, useRef, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import { Card, EmptyState, Pill, StatCard } from '../ui/components'
import { fmtNum } from '../ui/format'
import { CHART, HEALTH_LABEL, HEALTH_TONE, SOURCE_COLORS, nodeLabel } from '../ui/theme'
import { mockConsumptionKw } from '../mocks/uiMocks'

// Dashboard: live overview. Everything is derived from the existing Digital
// Twin hook (initial GET /twin/nodes + /twin/decisions, then WebSocket
// pushes). The chart and the stream panel are client-side buffers of those
// pushes; nothing here polls.

const MAX_POINTS = 60
const MAX_STREAM = 40

const isSource = (n) => n.type !== 'bus' && n.type !== 'grid'

function sumBy(nodes, pred, f) {
  return nodes.filter(pred).reduce((acc, n) => acc + (f(n) ?? 0), 0)
}

function snapshot(nodes) {
  const src = nodes.filter(isSource)
  const power = (n) => n.latest_reading?.power_output ?? 0
  return {
    wind: sumBy(src, (n) => n.type === 'wind', power),
    hydro: sumBy(src, (n) => n.type === 'hydro', power),
    solar: sumBy(src, (n) => n.type === 'solar', power),
    // Twin estimate of what currently reaches the grid: output of every
    // non-isolated source scaled by its load share (curtailment).
    grid: sumBy(src, (n) => !n.isolated, (n) => power(n) * (n.load_share ?? 1)),
  }
}

// Rows for the live stream panel, one per attribute of each new reading.
function readingRows(node) {
  const r = node.latest_reading
  const rows = [{ attr: 'Power output', value: `${fmtNum(r.power_output, 1)} kW` }]
  if (r.wind_speed != null) rows.push({ attr: 'Wind speed', value: `${fmtNum(r.wind_speed, 1)} m/s` })
  if (r.temperature != null) rows.push({ attr: 'Temperature', value: `${fmtNum(r.temperature, 1)} °C` })
  if (r.vibration != null) rows.push({ attr: 'Vibration', value: fmtNum(r.vibration, 2) })
  return rows
}

function useLiveBuffers(nodes) {
  const [series, setSeries] = useState([])
  const [stream, setStream] = useState([])
  const seen = useRef({})
  const lastPointAt = useRef(0)
  const seq = useRef(0)

  useEffect(() => {
    const list = Object.values(nodes)
    if (list.length === 0) return
    const fresh = []
    for (const n of list) {
      const ts = n.latest_reading?.timestamp
      if (!ts || !isSource(n)) continue
      if (seen.current[n.node_id] !== ts) {
        // The first snapshot seeds the "seen" map without flooding the panel.
        if (seen.current[n.node_id] !== undefined) fresh.push(n)
        seen.current[n.node_id] = ts
      }
    }
    if (fresh.length) {
      const now = new Date()
      const rows = fresh.flatMap((n) =>
        readingRows(n).map((row) => ({
          ...row,
          id: ++seq.current,
          node: n.node_id,
          type: n.type,
          replayed: n.source_type === 'historical',
          at: now.toLocaleTimeString(),
        })),
      )
      setStream((prev) => [...rows.reverse(), ...prev].slice(0, MAX_STREAM))
    }
    const t = Date.now()
    if (t - lastPointAt.current >= 1000) {
      lastPointAt.current = t
      setSeries((prev) =>
        [...prev, { time: new Date(t).toLocaleTimeString(), ...snapshot(list) }].slice(-MAX_POINTS),
      )
    }
  }, [nodes])

  return { series, stream }
}

function EnergyFlowChart({ series }) {
  if (series.length < 2) {
    return <EmptyState icon="pulse">Collecting live readings… the chart fills in as updates arrive.</EmptyState>
  }
  const hasSolar = series.some((p) => p.solar > 0)
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="time" stroke={CHART.axis} fontSize={12} tickLine={false} minTickGap={40} />
          <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => fmtNum(v)} />
          <Tooltip {...CHART.tooltip} formatter={(v) => `${fmtNum(v, 1)} kW`} />
          <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
          {hasSolar && <Line type="monotone" name="Solar" dataKey="solar" stroke={SOURCE_COLORS.solar} strokeWidth={2} dot={false} isAnimationActive={false} />}
          <Line type="monotone" name="Wind" dataKey="wind" stroke={SOURCE_COLORS.wind} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" name="Hydro" dataKey="hydro" stroke={SOURCE_COLORS.hydro} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" name="To grid" dataKey="grid" stroke={SOURCE_COLORS.grid} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function LiveStream({ stream }) {
  return (
    <Card title="Live data stream" subtitle="Newest first">
      {stream.length === 0 ? (
        <EmptyState>Waiting for the next reading…</EmptyState>
      ) : (
        <ul className="max-h-[328px] divide-y divide-slate-100 overflow-y-auto">
          {stream.map((row) => (
            <li key={row.id} className="sei-row-in flex items-center gap-3 py-2 text-sm">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: SOURCE_COLORS[row.type] ?? SOURCE_COLORS.grid }} />
              <span className="w-28 shrink-0 truncate text-slate-500" title={row.node}>
                {nodeLabel(row.node)}
              </span>
              <span className="flex-1 truncate">
                <span className="text-slate-500">{row.attr} : </span>
                <span className="font-semibold text-slate-900">{row.value}</span>
              </span>
              <span className="shrink-0 text-xs text-slate-400">{row.at}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-slate-500">Kelmarsh T1–T4 are replayed SCADA data; wind farm and hydro are the live API.</p>
    </Card>
  )
}

function LiveAlerts({ nodes, decisions }) {
  const flagged = nodes.filter((n) => isSource(n) && n.health_status && n.health_status !== 'normal')
  const items = [
    ...flagged.map((n) => ({
      key: `n-${n.node_id}`,
      tone: HEALTH_TONE[n.health_status],
      title: `${nodeLabel(n.node_id)}: ${HEALTH_LABEL[n.health_status]}`,
      sub: (n.flagged_by ?? []).includes('ta_gnn') ? 'Flagged by TA-GNN' : 'Flagged by rule-based detector',
    })),
    ...decisions.slice(0, 3).map((d, i) => ({
      key: `d-${i}-${d.time}`,
      tone: 'info',
      title: `Self-healing: ${nodeLabel(d.node_id)} ${d.chosen_action === 'reroute' ? 'rerouted' : d.chosen_action === 'isolate' ? 'isolated' : 'curtailed'}`,
      sub: new Date(d.time).toLocaleTimeString(),
    })),
  ].slice(0, 5)

  return (
    <Card title="Live alerts">
      {items.length === 0 ? (
        <EmptyState icon="check">All nodes normal.</EmptyState>
      ) : (
        <ul className="space-y-3">
          {items.map((a) => (
            <li key={a.key} className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-800">{a.title}</div>
                <div className="text-xs text-slate-500">{a.sub}</div>
              </div>
              <Pill tone={a.tone}>{a.tone === 'bad' ? 'Fault' : a.tone === 'warn' ? 'Warning' : 'Action'}</Pill>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export default function DashboardTab() {
  const { nodes, decisions, connected } = useDigitalTwinSocket()
  useReportConnection(connected)
  const list = useMemo(() => Object.values(nodes), [nodes])
  const { series, stream } = useLiveBuffers(nodes)

  const sources = list.filter(isSource)
  const generation = sumBy(sources, () => true, (n) => n.latest_reading?.power_output)
  const healthy = sources.filter((n) => (n.health_status ?? 'normal') === 'normal').length
  const active = sources.filter((n) => !n.isolated && n.latest_reading).length
  const stability = sources.length ? Math.round((healthy / sources.length) * 100) : null

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total generation" value={fmtNum(generation / 1000, 2)} unit="MW" icon="bolt" color="#14b8a6" hint="All sources, latest reading" />
        <StatCard label="Total consumption" value={fmtNum(mockConsumptionKw(generation) / 1000, 2)} unit="MW" icon="plug" color="#64748b" mock />
        <StatCard
          label="Grid stability"
          value={stability ?? '—'}
          unit="%"
          icon="gauge"
          color={stability == null || stability >= 80 ? '#16a34a' : stability >= 50 ? '#d97706' : '#dc2626'}
          hint={`${healthy} of ${sources.length} sources normal`}
        />
        <StatCard label="Active nodes" value={active} unit={`/ ${sources.length}`} icon="nodes" color="#4f46e5" hint="Connected and reporting" />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Energy flow" subtitle="Live output by source (kW)" className="xl:col-span-2">
          <EnergyFlowChart series={series} />
        </Card>
        <LiveAlerts nodes={list} decisions={decisions} />
      </div>

      <LiveStream stream={stream} />
    </div>
  )
}
