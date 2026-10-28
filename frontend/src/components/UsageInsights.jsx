import { useMemo } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, Pill } from '../ui/components'
import { fmtNum } from '../ui/format'
import { CHART } from '../ui/theme'
import { GRIDS, USAGE, USAGE_PROVENANCE, backtestMape, forecastNextDay } from '../data/gridUsage'

const COLORS = { grid_1: '#4f46e5', grid_2: '#14b8a6' }
const hh = (h) => `${String(h % 24).padStart(2, '0')}:00`

// Usage and prediction insights for the two main grids, from the small sample dataset in data/gridUsage.js.
export default function UsageInsights() {
  const { series, insights } = useMemo(() => {
    const per = GRIDS.map((g) => {
      const hist = USAGE[g.id]
      const forecast = forecastNextDay(hist)
      const last = hist.slice(-24)
      const peakIdx = forecast.indexOf(Math.max(...forecast))
      const sum = (a) => a.reduce((s, x) => s + x, 0)
      return {
        ...g,
        last,
        forecast,
        peakHour: hh(peakIdx),
        peakKw: forecast[peakIdx],
        todayMwh: sum(last) / 1000,
        nextMwh: sum(forecast) / 1000,
        mape: backtestMape(hist),
      }
    })
    const series = Array.from({ length: 48 }, (_, i) => {
      const p = { hour: hh(i % 24) }
      for (const g of per) p[i < 24 ? g.id : `${g.id}_f`] = i < 24 ? g.last[i] : g.forecast[i - 24]
      return p
    })
    return { series, insights: per }
  }, [])

  const totalNext = insights.reduce((s, g) => s + g.nextMwh, 0)
  const totalToday = insights.reduce((s, g) => s + g.todayMwh, 0)
  const change = ((totalNext - totalToday) / totalToday) * 100

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <Card title="Usage and prediction" subtitle="Last 24 h (solid) and next 24 h forecast (dashed), kW" className="xl:col-span-2">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="hour" stroke={CHART.axis} fontSize={12} tickLine={false} interval={5} />
              <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => fmtNum(v)} />
              <Tooltip {...CHART.tooltip} formatter={(v) => `${fmtNum(v, 0)} kW`} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: 13 }} />
              {GRIDS.map((g) => [
                <Line key={g.id} name={`${g.label} usage`} dataKey={g.id} stroke={COLORS[g.id]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />,
                <Line key={`${g.id}_f`} name={`${g.label} forecast`} dataKey={`${g.id}_f`} stroke={COLORS[g.id]} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />,
              ])}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-3 text-xs text-slate-500">{USAGE_PROVENANCE}. Forecast = seasonal average of the same hour over 7 days, not a trained model.</p>
      </Card>

      <Card title="Insights" action={<Pill tone="idle" dot={false}>Sample data</Pill>}>
        <ul className="space-y-4 text-sm">
          <li>
            <div className="text-xs text-slate-500">Next 24 h, both grids</div>
            <div className="font-semibold text-slate-900">
              {fmtNum(totalNext, 1)} MWh <span className="font-normal text-slate-500">({change >= 0 ? '+' : ''}{fmtNum(change, 1)}% vs last 24 h)</span>
            </div>
          </li>
          {insights.map((g) => (
            <li key={g.id} className="border-t border-slate-100 pt-3">
              <div className="flex items-center gap-2 font-medium text-slate-800">
                <span className="h-2 w-2 rounded-full" style={{ background: COLORS[g.id] }} />
                {g.label}
              </div>
              <div className="mt-1 text-slate-600">
                Peak {fmtNum(g.peakKw, 0)} kW at {g.peakHour} · {fmtNum(g.nextMwh, 1)} MWh next 24 h
              </div>
              <div className="text-xs text-slate-500">Backtest error {fmtNum(g.mape, 1)}% (last day predicted from the 6 before)</div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
