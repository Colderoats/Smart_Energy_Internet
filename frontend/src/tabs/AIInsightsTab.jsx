import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { apiFetch } from '../auth/api'
import { navigate } from '../auth/router'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import Icon from '../ui/icons'
import { Button, Card, Details, MockTag, Pill } from '../ui/components'
import { fmtNum } from '../ui/format'
import { ACCENT, CHART, HEALTH_LABEL, HEALTH_TONE, nodeLabel } from '../ui/theme'
import { mockDemandForecast24h } from '../mocks/uiMocks'

// AI Insights. Fault risk and detection come from the TA-GNN verdicts already
// on every twin node (`detectors`, `flagged_by`; live via twin_node_update)
// plus the model card from GET /ai/predictions (fetched once). TA-GNN output
// is a FORECAST on REPLAYED Kelmarsh SCADA data. The 24h demand forecast is a
// MOCK: no demand-forecast model exists.

function useModelCard() {
  const [model, setModel] = useState(null)
  useEffect(() => {
    let cancelled = false
    apiFetch('/ai/predictions')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => !cancelled && setModel(data?.model ?? null))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])
  return model
}

function riskLevel(scored, threshold) {
  const maxP = Math.max(0, ...scored.map((n) => n.detectors?.ta_gnn?.probability ?? 0))
  const anyFlag = scored.some((n) => n.detectors?.ta_gnn?.flagged)
  const anyFault = scored.some((n) => n.health_status === 'fault' || n.health_status === 'fault_predicted')
  const t = threshold ?? 0.5
  const faults = scored.filter((n) => n.health_status === 'fault' || n.health_status === 'fault_predicted').length
  if (anyFlag) return { level: 'High', tone: 'bad', maxP, reason: 'TA-GNN has flagged a node' }
  if (anyFault) return { level: 'High', tone: 'bad', maxP, reason: `${faults} node${faults === 1 ? ' is' : 's are'} already in a fault state` }
  if (maxP >= t / 2) return { level: 'Medium', tone: 'warn', maxP, reason: 'A node score is approaching the flag threshold' }
  if (scored.some((n) => n.health_status === 'warning')) return { level: 'Medium', tone: 'warn', maxP, reason: 'A node is in warning state' }
  return { level: 'Low', tone: 'ok', maxP, reason: 'No node is flagged or near the threshold' }
}

function recommendations(nodes) {
  const recs = []
  const sources = nodes.filter((n) => n.type !== 'bus' && n.type !== 'grid')
  for (const n of sources) {
    const gnn = n.detectors?.ta_gnn
    if (gnn?.flagged) {
      recs.push({
        key: `gnn-${n.node_id}`,
        tone: 'bad',
        title: `Inspect ${nodeLabel(n.node_id)}`,
        body: `TA-GNN gives a ${(gnn.probability * 100).toFixed(0)}% chance of a fault starting within ${gnn.horizon_min} min.`,
        action: 'View on Grid Map',
        go: '/dashboard/map?view=twin',
      })
    }
  }
  for (const b of nodes.filter((n) => n.type === 'bus' && n.current_load_kw > n.capacity_kw)) {
    recs.push({
      key: `bus-${b.node_id}`,
      tone: 'warn',
      title: `${nodeLabel(b.node_id)} is over capacity`,
      body: `${fmtNum(b.current_load_kw)} of ${fmtNum(b.capacity_kw)} kW. Review routing in the digital twin.`,
      action: 'Open Digital Twin',
      go: '/dashboard/map?view=twin',
    })
  }
  for (const n of sources.filter((s) => s.isolated || s.load_share < 1)) {
    recs.push({
      key: `iso-${n.node_id}`,
      tone: 'warn',
      title: `${nodeLabel(n.node_id)} is ${n.isolated ? 'isolated' : `curtailed to ${Math.round(n.load_share * 100)}%`}`,
      body: 'Restore full output once the fault has been inspected.',
      action: 'See redistribution',
      go: '/dashboard/chain',
    })
  }
  if (recs.length === 0) {
    recs.push({
      key: 'fl',
      tone: 'ok',
      title: 'All clear',
      body: 'No node is flagged. Review how the federated model was trained.',
      action: 'Open Federated Learning',
      go: '/dashboard/map?tab=fl',
    })
  }
  return recs.slice(0, 3)
}

export default function AIInsightsTab() {
  const { nodes, connected } = useDigitalTwinSocket()
  useReportConnection(connected)
  const model = useModelCard()
  const list = useMemo(() => Object.values(nodes), [nodes])
  const scored = list.filter((n) => n.detectors?.ta_gnn)
  const risk = riskLevel(scored, model?.operating_threshold_probability)
  const flagged = list.filter((n) => (n.flagged_by ?? []).length > 0)
  const recs = recommendations(list)

  const demand = useMemo(() => mockDemandForecast24h(), [])
  const peak = demand.reduce((a, p) => (p.kw > a.kw ? p : a), demand[0])

  const modelLabel = `TA-GNN${model?.source ? ` · ${model.source}` : ''}`

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Fault risk forecast" subtitle={`Next ${model?.horizon_min ?? 60} min`} action={<Pill tone="chain" dot={false}>{modelLabel}</Pill>}>
          <div className="flex items-end justify-between">
            <div>
              <div className="text-[32px] font-semibold leading-none text-slate-900">{risk.level}</div>
              <div className="mt-2 text-sm text-slate-600">{risk.reason}</div>
              <div className="text-sm text-slate-500">Highest TA-GNN score {(risk.maxP * 100).toFixed(1)}%</div>
            </div>
            <Pill tone={risk.tone}>{risk.level} risk</Pill>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full rounded-full ${risk.tone === 'bad' ? 'bg-red-500' : risk.tone === 'warn' ? 'bg-amber-500' : 'bg-emerald-500'}`}
              style={{ width: `${Math.max(3, risk.maxP * 100)}%` }}
            />
          </div>
          <div className="mt-4">
            <Details>
              <ul className="space-y-1.5 text-sm">
                {scored.map((n) => (
                  <li key={n.node_id} className="flex justify-between">
                    <span className="text-slate-600">{nodeLabel(n.node_id)}</span>
                    <span className={n.detectors.ta_gnn.flagged ? 'font-semibold text-red-600' : 'text-slate-800'}>
                      {(n.detectors.ta_gnn.probability * 100).toFixed(1)}%
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-slate-500">
                Forecast on replayed Kelmarsh SCADA data.
                {model?.operating_threshold_probability != null &&
                  ` Flag threshold ${(model.operating_threshold_probability * 100).toFixed(1)}%.`}
              </p>
            </Details>
          </div>
        </Card>

        <Card title="Fault detection" subtitle="Rule-based + TA-GNN, side by side">
          <div className="flex items-center gap-4">
            <span
              className={`flex h-12 w-12 items-center justify-center rounded-2xl ${flagged.length ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-600'}`}
            >
              <Icon name={flagged.length ? 'alert' : 'check'} size={24} />
            </span>
            <div>
              <div className="text-[32px] font-semibold leading-none text-slate-900">{flagged.length}</div>
              <div className="mt-1 text-sm text-slate-500">node{flagged.length === 1 ? '' : 's'} flagged now</div>
            </div>
          </div>
          <div className="mt-4">
            <Details>
              {flagged.length === 0 ? (
                <p className="text-sm text-slate-500">No detector has flagged a node.</p>
              ) : (
                <ul className="space-y-2">
                  {flagged.map((n) => (
                    <li key={n.node_id} className="flex items-center justify-between gap-2 text-sm">
                      <span className="text-slate-700">{nodeLabel(n.node_id)}</span>
                      <span className="flex gap-1.5">
                        <Pill tone={HEALTH_TONE[n.health_status] ?? 'idle'}>{HEALTH_LABEL[n.health_status] ?? n.health_status}</Pill>
                        <span className="text-xs text-slate-500">{n.flagged_by.map((f) => (f === 'ta_gnn' ? 'TA-GNN' : 'rule')).join(' + ')}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Details>
          </div>
        </Card>

        <Card title="Demand forecast" subtitle="Next 24 hours" action={<MockTag />}>
          <div className="text-sm text-slate-500">
            Peak at <span className="font-semibold text-slate-900">{peak.hour}</span> · {fmtNum(peak.kw)} kW
          </div>
          <div className="mt-2 h-36">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={demand} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <defs>
                  <linearGradient id="demandFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor={ACCENT} stopOpacity={0.25} />
                    <stop offset="1" stopColor={ACCENT} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="hour" stroke={CHART.axis} fontSize={11} tickLine={false} interval={5} />
                <YAxis stroke={CHART.axis} fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip {...CHART.tooltip} formatter={(v) => `${fmtNum(v)} kW`} />
                <Area dataKey="kw" stroke={ACCENT} strokeWidth={2} fill="url(#demandFill)" />
                <ReferenceDot x={peak.hour} y={peak.kw} r={5} fill="#dc2626" stroke="#fff" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div>
        <h2 className="mb-3 text-base font-semibold text-slate-800">Recommendations</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {recs.map((r) => (
            <div key={r.key} className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_1px_3px_rgba(15,23,42,0.06)]">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[15px] font-semibold text-slate-900">{r.title}</span>
                <Pill tone={r.tone} dot={false}>
                  {r.tone === 'bad' ? 'Urgent' : r.tone === 'warn' ? 'Review' : 'OK'}
                </Pill>
              </div>
              <p className="mt-2 flex-1 text-sm text-slate-600">{r.body}</p>
              <Button variant="secondary" className="mt-4 self-start" onClick={() => navigate(r.go)}>
                {r.action}
              </Button>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">Model source: {modelLabel}. Recommendations are rules over the current twin state.</p>
      </div>
    </div>
  )
}
