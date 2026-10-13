import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, EmptyState } from '../ui/components'
import { CHART } from '../ui/theme'
import { ErrorNote, Loading, SimPill } from '../testbed/common'
import { useTestbed } from '../testbed/useTestbed'

// Graphs: every paper figure and extra comparison charts, drawn from saved measured runs (/testbed/graphs).
// Each chart carries a caption: the paper figure/table it reproduces, one line on what it shows, and the run id.

const PALETTE = ['#4f46e5', '#14b8a6', '#f59e0b', '#dc2626', '#7c3aed', '#3b82f6', '#64748b', '#16a34a']

function Chart({ c }) {
  const series = c.series ?? []
  const common = { data: c.data, margin: { top: 8, right: 16, left: 4, bottom: 4 } }
  const axes = (
    <>
      <CartesianGrid stroke={CHART.grid} strokeDasharray="3 3" />
      <XAxis dataKey={c.xKey} stroke={CHART.axis} tick={{ fontSize: 11 }} label={c.xLabel ? { value: c.xLabel, position: 'insideBottom', offset: -2, fontSize: 11, fill: CHART.axis } : undefined} />
      <YAxis stroke={CHART.axis} tick={{ fontSize: 11 }} scale={c.logY ? 'log' : 'auto'} domain={c.logY ? ['auto', 'auto'] : undefined} allowDataOverflow={Boolean(c.logY)}
        label={c.yLabel ? { value: c.yLabel, angle: -90, position: 'insideLeft', fontSize: 11, fill: CHART.axis } : undefined} />
      <Tooltip {...CHART.tooltip} />
      <Legend wrapperStyle={{ fontSize: 12 }} />
    </>
  )
  const col = (s, i) => s.color ?? PALETTE[i % PALETTE.length]
  return (
    <div className="h-[300px]" role="img" aria-label={c.title}>
      <ResponsiveContainer width="100%" height="100%">
        {c.kind === 'bar' ? (
          <BarChart {...common}>{axes}{series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={col(s, i)} radius={[4, 4, 0, 0]} />)}</BarChart>
        ) : c.kind === 'area' ? (
          <AreaChart {...common}>{axes}{series.map((s, i) => <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={col(s, i)} fill={col(s, i)} fillOpacity={0.18} dot={false} stackId={c.stack ? 'a' : undefined} />)}</AreaChart>
        ) : (
          <LineChart {...common}>{axes}{series.map((s, i) => <Line key={s.key} type={c.step ? 'stepAfter' : 'monotone'} dataKey={s.key} name={s.label} stroke={col(s, i)} dot={c.dots ?? false} strokeWidth={2} connectNulls />)}</LineChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}

export default function GraphsTab() {
  const { data, error, loading } = useTestbed('/testbed/graphs')
  if (loading) return <div className="p-6"><Loading what="graphs" /></div>
  if (error) return <div className="mx-auto max-w-7xl p-6"><ErrorNote error={error} /></div>
  const groups = {}
  for (const c of data.charts) (groups[c.group] ??= []).push(c)
  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <p className="max-w-3xl text-sm text-slate-500">Paper figures recreated from measured runs on the simulated testbed, plus extra comparison charts. Captions name the figure or table reproduced and the run that produced the data.</p>
      {data.charts.length === 0 && <EmptyState>No graphs exported yet.</EmptyState>}
      {Object.entries(groups).map(([g, cs]) => (
        <section key={g} className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">{g}</h2>
          <div className="grid gap-4 xl:grid-cols-2">
            {cs.map((c) => (
              <Card key={c.id} title={c.title} action={<SimPill />}>
                <Chart c={c} />
                <p className="mt-2 text-xs text-slate-600"><span className="font-semibold">{c.reproduces}.</span> {c.caption}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">Run: <span className="font-mono">{c.run_id}</span></p>
              </Card>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
