import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { apiFetch } from '../auth/api'
import { navigate } from '../auth/router'
import { CopyButton, Pill } from '../ui/components'
import { fmtNum, shortHash } from '../ui/format'
import { SourceIcon } from '../ui/icons'
import { CHART, CHAIN_COLOR, SOURCE_COLORS, nodeLabel } from '../ui/theme'
import { OnChainChip, ProvenanceBadges } from './TwinNode'

// Digital Twin side panel for a prosumer (a SIMULATED building): 24 h generation vs
// consumption, its market trades and its on-chain address / records. Generation is
// estimated from live weather (or a demo irradiance), consumption is synthetic.

const ROLE_TONE = { surplus: 'ok', deficit: 'warn', balanced: 'idle' }

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{children}</span>
    </div>
  )
}

function Series({ nodeId, latest }) {
  const [points, setPoints] = useState([])
  useEffect(() => {
    let cancelled = false
    setPoints([])
    apiFetch(`/market/prosumers/${nodeId}/series?hours=24`)
      .then((r) => r.json())
      .then((d) => !cancelled && setPoints((d.points ?? []).map((p) => ({ ...p, t: new Date(p.time).getTime() }))))
      .catch((err) => console.error('Failed to load prosumer series', err))
    return () => {
      cancelled = true
    }
  }, [nodeId])

  const live = latest?.timestamp && latest.generation_kw != null ? [{ t: new Date(latest.timestamp).getTime(), generation_kw: latest.generation_kw, consumption_kw: latest.consumption_kw }] : []
  const data = [...points, ...live.filter((p) => !points.length || p.t > points[points.length - 1].t)]
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" stroke={CHART.axis} fontSize={11} tickLine={false} minTickGap={40}
            tickFormatter={(t) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
          <YAxis stroke={CHART.axis} fontSize={11} tickLine={false} axisLine={false} width={36} unit=" kW" />
          <Tooltip {...CHART.tooltip} labelFormatter={(t) => new Date(t).toLocaleString()} formatter={(v) => `${Number(v).toFixed(2)} kW`} />
          <Line type="monotone" name="Generation (estimated)" dataKey="generation_kw" stroke={SOURCE_COLORS.solar} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line type="monotone" name="Consumption (simulated)" dataKey="consumption_kw" stroke="#475569" strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function ProsumerPanel({ node, info, trades }) {
  if (!node) return null
  const mine = (trades ?? []).filter((t) => t.seller === node.node_id || t.buyer === node.node_id).slice(0, 6)
  const reg = info?.registration
  const addr = info?.address ?? reg?.address
  return (
    <div>
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: `${SOURCE_COLORS.solar}1f`, color: SOURCE_COLORS.solar }}>
          <SourceIcon type={node.profile} size={22} />
        </span>
        <div className="min-w-0">
          <div className="truncate text-base font-semibold text-slate-900">{nodeLabel(node.node_id)}</div>
          <div className="truncate font-mono text-xs text-slate-400">{node.node_id}</div>
        </div>
        <Pill tone={ROLE_TONE[node.role] ?? 'idle'} className="ml-auto">{(node.role ?? 'balanced').toUpperCase()}</Pill>
      </div>
      <div className="mt-3"><ProvenanceBadges node={node} /></div>
      <div className="mt-3 divide-y divide-slate-100">
        <Row label="Generation (estimated)"><span style={{ color: SOURCE_COLORS.solar }}>{fmtNum(node.generation_kw, 2)} kW</span></Row>
        <Row label="Consumption (simulated)">{fmtNum(node.consumption_kw, 2)} kW</Row>
        <Row label="Net">{node.net_kw == null ? '—' : `${node.net_kw > 0 ? '+' : ''}${node.net_kw.toFixed(2)} kW`}</Row>
        <Row label="Rooftop PV">{node.pv_kwp} kWp</Row>
        {node.latest_reading?.irradiance_wm2 != null && <Row label={node.provenance_detail?.demo_irradiance ? 'Irradiance (demo)' : 'Irradiance (live)'}>{fmtNum(node.latest_reading.irradiance_wm2)} W/m²</Row>}
        {info?.ask != null && <Row label="Ask / max price">{info.ask} / {info.max} <span className="text-xs text-slate-400">demo credits/kWh</span></Row>}
      </div>

      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Last 24 h · generation vs consumption</div>
      <Series nodeId={node.node_id} latest={node} />

      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">On-chain</div>
      <div className="space-y-1.5 text-sm">
        <div className="flex items-center gap-2">
          <OnChainChip onchain={node.onchain} nodeId={node.node_id} />
          {reg?.gas_used != null && <span className="text-xs text-slate-500">registration gas {fmtNum(reg.gas_used)}</span>}
        </div>
        {addr && (
          <div className="flex items-center gap-1 font-mono text-xs text-slate-600">
            {shortHash(addr, 8)}
            <CopyButton text={addr} label="Copy address" />
          </div>
        )}
        {reg?.tx_hash && <div className="font-mono text-xs text-slate-500">registration tx {shortHash(reg.tx_hash)}</div>}
        {info?.balance_milli != null && <div className="text-xs text-slate-500">Balance: {fmtNum(info.balance_milli / 1000, 3)} demo credits</div>}
        <button
          onClick={() => navigate(`/dashboard/chain?registration=${node.node_id}`)}
          className="text-xs font-medium text-violet-700 hover:underline"
          style={{ color: CHAIN_COLOR }}
        >
          Open records in the Blockchain view →
        </button>
      </div>

      <div className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Its trades</div>
      {mine.length === 0 ? (
        <p className="text-sm text-slate-500">No trades yet.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
          {mine.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-2 py-1.5">
              <span className="min-w-0 truncate">
                {t.seller === node.node_id ? `sold to ${nodeLabel(t.buyer)}` : `bought from ${nodeLabel(t.seller)}`}
              </span>
              <span className="shrink-0 text-xs text-slate-500">
                {fmtNum(((t.settled_wh ?? t.matched_wh) ?? 0) / 1000, 3)} kWh · {t.status === 'settled' ? `block #${t.settle_block}` : t.status.replace('_', ' ')}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
