import { useEffect, useState } from 'react'
import { Line, LineChart, ResponsiveContainer, YAxis } from 'recharts'
import { apiFetch } from '../auth/api'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import { SourceIcon } from '../ui/icons'
import { EmptyState, Pill, Segmented } from '../ui/components'
import { fmtNum } from '../ui/format'
import { HEALTH_LABEL, HEALTH_TONE, SOURCE_COLORS } from '../ui/theme'
import NodeSidePanel from '../components/NodeSidePanel'

// Sources: one card per generating node from the Digital Twin (GET /twin/nodes
// + pushes). Sparkline = GET /twin/nodes/{id}/history (existing endpoint)
// plus live-appended readings. Efficiency = output / rated capacity.

const GROUPS = [
  { type: 'wind', title: 'Turbines (wind)' },
  { type: 'hydro', title: 'Hydro plants' },
  { type: 'solar', title: 'Solar plants' },
]

function Sparkline({ nodeId, reading, color }) {
  const [points, setPoints] = useState([])
  useEffect(() => {
    let cancelled = false
    apiFetch(`/twin/nodes/${nodeId}/history?limit=30`)
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled) setPoints([...(data.history ?? [])].reverse().map((r) => ({ v: r.normalized?.power_output ?? 0 })))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [nodeId])
  useEffect(() => {
    if (reading?.normalized?.power_output != null) setPoints((p) => [...p, { v: reading.normalized.power_output }].slice(-40))
  }, [reading?.timestamp, reading?.normalized?.power_output])
  if (points.length < 2) return <div className="h-12" />
  return (
    <div className="h-12">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <YAxis hide domain={['dataMin', 'dataMax']} />
          <Line dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function SourceCard({ node, open, onToggle }) {
  const r = node.latest_reading
  const color = SOURCE_COLORS[node.type] ?? SOURCE_COLORS.grid
  const online = !!r && !node.isolated
  const eff = r && node.rated_capacity_kw ? Math.min(100, (r.power_output / node.rated_capacity_kw) * 100) : null
  const health = node.health_status ?? 'normal'
  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-[0_1px_3px_rgba(15,23,42,0.06)]">
      <button onClick={onToggle} className="w-full p-5 text-left" aria-expanded={open}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: `${color}1f`, color }}>
              <SourceIcon type={node.type} size={20} />
            </span>
            <div className="leading-tight">
              <div className="text-[15px] font-semibold text-slate-900">{node.name}</div>
              <div className="text-xs text-slate-500">{r?.provenance === 'sensed' || node.node_id === 'solar_hardware' ? 'Sensed · ESP32 + INA219' : node.source_type === 'live' ? 'Live API' : node.source_type === 'simulated' ? 'Replayed sample' : 'Replayed SCADA'}</div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <Pill>{online ? 'Online' : 'Offline'}</Pill>
            {health !== 'normal' && <Pill tone={HEALTH_TONE[health]}>{HEALTH_LABEL[health]}</Pill>}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4">
          <div>
            <div className="text-sm text-slate-500">Current output (normalized)</div>
            <div className="mt-0.5 text-2xl font-semibold text-slate-900">
              {r?.normalized?.power_output != null ? fmtNum(r.normalized.power_output, 3) : '—'} <span className="text-sm font-medium text-slate-500">p.u.</span>
            </div>
          </div>
          <div>
            <div className="text-sm text-slate-500">Efficiency</div>
            <div className="mt-0.5 text-2xl font-semibold text-slate-900">
              {eff == null ? '—' : Math.round(eff)} <span className="text-sm font-medium text-slate-500">%</span>
            </div>
          </div>
        </div>
        {(r?.provenance === 'sensed' || node.node_id === 'solar_hardware') && (
          <div className="mt-3 grid grid-cols-3 gap-3 text-xs text-slate-500">
            {[['Voltage', r?.normalized?.voltage, r?.voltage_v, 'V'], ['Current', r?.normalized?.current, r?.current_ma, 'mA'], ['Power', r?.normalized?.power_output, r?.power_output != null ? r.power_output * 1e6 : null, 'mW']].map(([label, pu, raw, unit]) => (
              <div key={label}>
                <div>{label} (p.u.)</div>
                <div className="text-sm font-semibold text-slate-900">{pu != null ? fmtNum(pu, 3) : '—'}</div>
                <div>{raw != null ? `${fmtNum(raw, 2)} ${unit}` : '—'}</div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-3">
          <Sparkline nodeId={node.node_id} reading={r} color={color} />
        </div>
      </button>
      {open && (
        <div className="border-t border-slate-100 p-5">
          <NodeSidePanel node={node} twin />
        </div>
      )}
    </div>
  )
}

export default function SourcesTab() {
  const { nodes, connected } = useDigitalTwinSocket()
  useReportConnection(connected)
  const [filter, setFilter] = useState('all')
  const [open, setOpen] = useState(null)

  const sources = Object.values(nodes)
    .filter((n) => n.type !== 'bus' && n.type !== 'grid' && n.type !== 'prosumer')
    .map((n) => ({
      ...n,
      name: n.node_id === 'solar_hardware'
        ? 'Solar hardware'
        : n.node_id.startsWith('wind_scada_kelmarsh_')
        ? `Kelmarsh turbine ${n.node_id.slice(-1)}`
        : n.type === 'hydro'
          ? 'Hydro plant'
          : n.type === 'solar'
            ? 'Solar plant'
            : 'Wind farm',
    }))

  return (
    <div className="mx-auto max-w-7xl space-y-8 p-6">
      <Segmented
        options={[
          { id: 'all', label: 'All' },
          { id: 'wind', label: 'Wind' },
          { id: 'hydro', label: 'Hydro' },
          { id: 'solar', label: 'Solar' },
        ]}
        value={filter}
        onChange={setFilter}
      />
      {GROUPS.filter((g) => filter === 'all' || filter === g.type).map((g) => {
        const items = sources.filter((s) => s.type === g.type)
        return (
          <section key={g.type}>
            <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-slate-800">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: SOURCE_COLORS[g.type] }} />
              {g.title}
              <span className="text-sm font-normal text-slate-400">{items.length}</span>
            </h2>
            {items.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-white">
                <EmptyState icon={g.type === 'solar' ? 'solar' : 'sources'}>
                  {g.type === 'solar' ? 'No solar plants connected yet.' : 'No sources of this type.'}
                </EmptyState>
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {items.map((n) => (
                  <SourceCard key={n.node_id} node={n} open={open === n.node_id} onToggle={() => setOpen(open === n.node_id ? null : n.node_id)} />
                ))}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
