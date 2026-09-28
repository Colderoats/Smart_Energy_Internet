import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useBlockchainSocket } from '../hooks/useBlockchainSocket'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import Icon from '../ui/icons'
import { Card, Details, EmptyState, MockTag, Segmented, StatCard } from '../ui/components'
import { fmtNum } from '../ui/format'
import { ACCENT, CHART, SOURCE_COLORS, SOURCE_LABELS } from '../ui/theme'
import {
  FL_BASELINE_COMPARISON,
  MOCK_CO2_TONNES_PER_MWH,
  MOCK_DOWNTIME_MIN_PER_HEAL,
  MOCK_GRID_DEPENDENCY,
  mockCostSeries,
} from '../mocks/uiMocks'

// Analytics: "what are we saving". Real where a source exists:
//  - energy redistributed: sum of P2P_TRADE kWh on the ledger (trades are simulated)
//  - generation mix: current twin node outputs by type
//  - self-healing events: twin decision log (GET /twin/decisions, newest 50)
//  - FedAvg vs SEI: measured, RESULTS.md snapshot
// Money, CO2, grid dependency and the cost chart are MOCK (no billing,
// metering or emissions data exists).

const RANGES = [
  { id: 7, label: '7 days' },
  { id: 30, label: '30 days' },
]

function bucket(series, size) {
  const out = []
  for (let i = 0; i < series.length; i += size) {
    const chunk = series.slice(i, i + size)
    out.push({
      label: chunk[0].label,
      grid: chunk.reduce((a, p) => a + p.grid, 0),
      sei: chunk.reduce((a, p) => a + p.sei, 0),
    })
  }
  return out
}

export default function AnalyticsTab() {
  const [range, setRange] = useState(7)
  const [grain, setGrain] = useState('daily')
  const { nodes, decisions, connected } = useDigitalTwinSocket()
  const { records: trades } = useBlockchainSocket('P2P_TRADE')
  useReportConnection(connected)

  const rangeSeries = useMemo(() => mockCostSeries(range), [range])
  const chartSeries = useMemo(() => {
    if (grain === 'daily') return rangeSeries
    if (grain === 'weekly') return bucket(mockCostSeries(84), 7)
    return bucket(mockCostSeries(180), 30)
  }, [grain, rangeSeries])

  const moneySaved = rangeSeries.reduce((a, p) => a + (p.grid - p.sei), 0)
  const mwh = rangeSeries.reduce((a, p) => a + p.kwh, 0) / 1000
  const co2 = mwh * MOCK_CO2_TONNES_PER_MWH

  const since = Date.now() - range * 86400_000
  const tradesInRange = trades.filter((r) => new Date(r.created_at).getTime() >= since)
  const redistributedKwh = tradesInRange.reduce((a, r) => a + (r.payload?.kwh ?? 0), 0)

  const heals = decisions.filter((d) => new Date(d.time).getTime() >= since)
  const resolved = heals.filter((d) => d.chosen_action === 'reroute').length

  const mix = useMemo(() => {
    const byType = {}
    for (const n of Object.values(nodes)) {
      if (n.type === 'bus' || n.type === 'grid') continue
      byType[n.type] = (byType[n.type] ?? 0) + (n.latest_reading?.power_output ?? 0)
    }
    return Object.entries(byType)
      .filter(([, v]) => v > 0)
      .map(([type, value]) => ({ type, name: SOURCE_LABELS[type] ?? type, value }))
  }, [nodes])
  const mixTotal = mix.reduce((a, m) => a + m.value, 0)

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">How much the platform is saving, compared with buying everything from the grid.</p>
        <Segmented options={RANGES} value={range} onChange={setRange} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Money saved" value={`₹ ${fmtNum(moneySaved)}`} icon="rupee" color="#16a34a" mock />
        <StatCard
          label="Energy redistributed"
          value={fmtNum(redistributedKwh, 1)}
          unit="kWh"
          icon="chain"
          color="#7c3aed"
          hint={`${tradesInRange.length} simulated trade${tradesInRange.length === 1 ? '' : 's'} on the ledger`}
        />
        <StatCard label="CO₂ avoided" value={fmtNum(co2, 1)} unit="tons" icon="leaf" color="#14b8a6" mock />
        <StatCard
          label="Grid dependency reduced"
          value={MOCK_GRID_DEPENDENCY.beforePct - MOCK_GRID_DEPENDENCY.withSeiPct}
          unit="%"
          icon="grid"
          color="#64748b"
          mock
        />
      </div>

      <Card
        title="Cost: with SEI vs grid only"
        subtitle="Rupees per period"
        action={
          <div className="flex items-center gap-2">
            <MockTag />
            <Segmented
              size="sm"
              options={[
                { id: 'daily', label: 'Daily' },
                { id: 'weekly', label: 'Weekly' },
                { id: 'monthly', label: 'Monthly' },
              ]}
              value={grain}
              onChange={setGrain}
            />
          </div>
        }
      >
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartSeries} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="label" stroke={CHART.axis} fontSize={12} tickLine={false} minTickGap={24} />
              <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} width={72} tickFormatter={(v) => `₹${fmtNum(v / 1000)}k`} />
              <Tooltip {...CHART.tooltip} formatter={(v) => `₹ ${fmtNum(v)}`} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
              <Line name="Grid only" dataKey="grid" stroke="#94a3b8" strokeWidth={2} dot={false} />
              <Line name="With SEI" dataKey="sei" stroke="#16a34a" strokeWidth={2.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Generation mix" subtitle="Current output by source">
          {mix.length === 0 ? (
            <EmptyState>No generation data yet.</EmptyState>
          ) : (
            <>
              <div className="relative h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={mix} dataKey="value" nameKey="name" innerRadius={58} outerRadius={84} paddingAngle={2} stroke="none">
                      {mix.map((m) => (
                        <Cell key={m.type} fill={SOURCE_COLORS[m.type] ?? SOURCE_COLORS.grid} />
                      ))}
                    </Pie>
                    <Tooltip {...CHART.tooltip} formatter={(v) => `${fmtNum(v)} kW`} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-2xl font-semibold text-slate-900">{fmtNum(mixTotal / 1000, 1)}</span>
                  <span className="text-xs text-slate-500">MW total</span>
                </div>
              </div>
              <ul className="mt-2 space-y-1.5">
                {mix.map((m) => (
                  <li key={m.type} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: SOURCE_COLORS[m.type] }} />
                      {m.name}
                    </span>
                    <span className="font-medium text-slate-700">{Math.round((m.value / mixTotal) * 100)}%</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-slate-500">No solar plants connected yet.</p>
            </>
          )}
        </Card>

        <Card title="Self-healing" subtitle={`Last ${range} days (twin decision log)`}>
          <div className="flex items-center gap-4">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-50 text-teal-600">
              <Icon name="heal" size={24} />
            </span>
            <div>
              <div className="text-[30px] font-semibold leading-none text-slate-900">{heals.length}</div>
              <div className="mt-1 text-sm text-slate-500">faults handled automatically</div>
            </div>
          </div>
          <div className="mt-5 space-y-2.5 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Resolved by reroute</span>
              <span className="font-medium">{resolved}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Isolated / curtailed</span>
              <span className="font-medium">{heals.length - resolved}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Est. downtime avoided</span>
              <span className="flex items-center gap-2 font-medium">
                <MockTag label="Estimate" />
                {fmtNum((heals.length * MOCK_DOWNTIME_MIN_PER_HEAL) / 60, 1)} h
              </span>
            </div>
          </div>
          <p className="mt-4 text-xs text-slate-500">Actions are applied to the digital twin only; nothing physical is switched.</p>
        </Card>

        <Card title="Baseline vs SEI" subtitle="FedAvg vs FedProx + adaptive weighting">
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={FL_BASELINE_COMPARISON} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="metric" stroke={CHART.axis} fontSize={11} tickLine={false} interval={0} />
                <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip {...CHART.tooltip} formatter={(v) => fmtNum(v, 3)} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
                <Bar name="FedAvg" dataKey="fedavg" fill="#cbd5e1" radius={[6, 6, 0, 0]} />
                <Bar name="SEI" dataKey="sei" fill={ACCENT} radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <Details label="Source">
            <p className="text-sm text-slate-600">
              Measured, mean of 5 seeds, from backend/ai/federated/artifacts/RESULTS.md (clean scenario). Test-set PR-AUC
              stays near chance (≈0.0003) for every configuration, so these are relative gains, not production accuracy.
            </p>
          </Details>
        </Card>
      </div>
    </div>
  )
}
