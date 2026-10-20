import { Handle, Position } from '@xyflow/react'
import { navigate } from '../auth/router'
import Icon, { SourceIcon } from '../ui/icons'
import { HEALTH_LABEL, HEALTH_TONE, SOURCE_COLORS, STATUS_COLORS, nodeLabel } from '../ui/theme'
import { SourceBadge } from './EnergyNode'

// Module 3: which detector said what. Rule-based (Module 2) and TA-GNN run side
// by side; `flagged_by` says which one(s) raised the current flag. TA-GNN output
// is a forecast on REPLAYED SCADA data, and the rule-based "fault" on replayed
// nodes is usually the replayed status-log label, not a statistic.
// Rendered in the Grid Map side panel for the selected node (kept off the
// node card to declutter the graph).
export function DetectorRows({ data }) {
  const detectors = data.detectors
  if (!detectors) return null
  const rule = detectors.rule_based
  const gnn = detectors.ta_gnn
  const flaggedBy = data.flagged_by ?? []
  const fromLabel = rule?.basis === 'replayed_ground_truth_label'

  return (
    <div className="space-y-2 text-sm">
      {flaggedBy.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {flaggedBy.includes('ta_gnn') && (
            <span className="rounded-md bg-violet-100 px-2 py-0.5 text-xs font-semibold text-violet-700">Flagged: TA-GNN</span>
          )}
          {flaggedBy.includes('rule_based') && (
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">Flagged: rule-based</span>
          )}
        </div>
      )}
      {rule && (
        <div
          className="flex justify-between gap-2"
          title={
            fromLabel
              ? 'Set by the replayed SCADA status log (ground-truth label), not by a statistic or a prediction'
              : 'Module 2 rolling temperature z-score rule'
          }
        >
          <span className="text-slate-500">Rule-based</span>
          <span className={rule.flagged ? 'font-semibold text-amber-700' : 'text-slate-700'}>
            {rule.flagged ? (fromLabel ? 'FAULT (replayed label)' : 'FLAG') : 'clear'}
          </span>
        </div>
      )}
      {gnn && (
        <div
          className="flex justify-between gap-2"
          title={`${gnn.model}: probability that a fault starts within ${gnn.horizon_min} min. Forecast on replayed SCADA data, not sensed.`}
        >
          <span className="text-slate-500">TA-GNN</span>
          <span className={gnn.flagged ? 'font-semibold text-violet-700' : 'text-slate-700'}>
            {gnn.flagged
              ? `FLAG ${(gnn.probability * 100).toFixed(0)}% ≤${gnn.horizon_min}min`
              : `${(gnn.probability * 100).toFixed(1)}%`}
          </span>
        </div>
      )}
    </div>
  )
}

function SourceNode({ data, selected }) {
  const tone = HEALTH_TONE[data.health_status] ?? 'ok'
  const statusColor = data.isolated ? STATUS_COLORS.bad : STATUS_COLORS[tone]
  const reading = data.latest_reading
  const curtailed = data.load_share < 1
  const color = SOURCE_COLORS[data.type] ?? SOURCE_COLORS.grid
  const gnnFlag = (data.flagged_by ?? []).includes('ta_gnn')

  return (
    <div
      className={`min-w-[176px] cursor-pointer rounded-2xl border-2 bg-white px-3 py-2.5 text-slate-800 shadow-sm transition-shadow hover:shadow-md ${
        selected ? 'ring-4 ring-indigo-100' : ''
      } ${data.isolated ? 'border-dashed opacity-80' : ''}`}
      style={{ borderColor: statusColor }}
      onClick={() => data.onSelect?.(data.node_id)}
      title={`${data.node_id} · ${HEALTH_LABEL[data.health_status] ?? 'Normal'}`}
    >
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: `${color}1f`, color }}>
          <SourceIcon type={data.type} size={19} />
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-sm font-semibold">{nodeLabel(data.node_id)}</div>
          <div className="text-sm text-slate-600">{reading?.normalized ? `${reading.normalized.power_output.toFixed(2)} p.u.` : '—'}</div>
        </div>
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: statusColor }} />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <SourceBadge sourceType={data.source_type} />
        {gnnFlag && <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-violet-700">TA-GNN</span>}
        {data.isolated && <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-700">Isolated</span>}
        {!data.isolated && curtailed && (
          <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-700">
            {Math.round(data.load_share * 100)}%
          </span>
        )}
      </div>
    </div>
  )
}

function BusNode({ data, selected }) {
  const overloaded = data.current_load_kw > data.capacity_kw
  const pct = Math.min(100, (data.current_load_kw / data.capacity_kw) * 100)

  return (
    <div
      className={`min-w-[170px] cursor-pointer rounded-2xl border-2 bg-white px-3 py-2.5 text-slate-800 shadow-sm ${
        overloaded ? 'border-red-500' : 'border-slate-300'
      } ${selected ? 'ring-4 ring-indigo-100' : ''}`}
      onClick={() => data.onSelect?.(data.node_id)}
    >
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <div className="flex items-center gap-2">
        <Icon name="bus" size={18} className="text-slate-500" />
        <span className="text-sm font-semibold">{nodeLabel(data.node_id)}</span>
        {overloaded && <span className="ml-auto text-[10px] font-semibold uppercase text-red-600">Overloaded</span>}
      </div>
      <div className="mt-1 text-xs text-slate-500">
        {data.current_load_kw.toFixed(0)} / {data.capacity_kw.toFixed(0)} kW
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full ${overloaded ? 'bg-red-500' : 'bg-slate-500'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function GridNode({ data }) {
  return (
    <div className="flex min-w-[120px] items-center gap-2 rounded-2xl border-2 border-slate-400 bg-slate-800 px-3 py-2.5 text-sm font-semibold text-white shadow-sm">
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle id="grid-out" type="source" position={Position.Bottom} className="invisible" />
      <Icon name="grid" size={18} />
      {nodeLabel(data.node_id)}
    </div>
  )
}

const ROLE_PILL = {
  surplus: { label: 'SURPLUS', cls: 'bg-emerald-100 text-emerald-700' },
  deficit: { label: 'DEFICIT', cls: 'bg-amber-100 text-amber-700' },
  balanced: { label: 'BALANCED', cls: 'bg-slate-100 text-slate-600' },
}

// Provenance badges for a prosumer (simulated building): solar is ESTIMATED from live
// weather (or a made-up demo irradiance), load is SYNTHETIC. Never shown as sensed.
export function ProvenanceBadges({ node }) {
  const d = node.provenance_detail
  const sensed = node.provenance === 'sensed'
  return (
    <div className="flex flex-wrap gap-1">
      {sensed ? (
        <span className="rounded border border-emerald-300 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">Sensed</span>
      ) : d?.demo_irradiance ? (
        <span className="rounded border border-amber-400 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700" title="PROSUMER_IRRADIANCE_OVERRIDE is set: the irradiance is made up (dev demo aid)">
          Demo irradiance
        </span>
      ) : node.provenance ? (
        <span className="rounded border border-amber-300 px-1.5 py-0.5 text-[10px] font-medium text-amber-700" title="Real Open-Meteo irradiance + temperature; PV output is an estimate">
          Estimated solar · live weather
        </span>
      ) : null}
      {!sensed && (
        <span className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-medium text-slate-600" title="Deterministic synthetic load profile">
          Simulated load
        </span>
      )}
    </div>
  )
}

export function OnChainChip({ onchain, nodeId }) {
  if (!onchain || !['in_block', 'confirmed'].includes(onchain.status)) {
    return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">Not on-chain yet</span>
  }
  return (
    <a
      href={`/dashboard/chain?registration=${nodeId}`}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        navigate(`/dashboard/chain?registration=${nodeId}`)
      }}
      className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-700 hover:bg-violet-200"
      title={`Registered on the EnergyMarket contract at ${onchain.address} (tx ${onchain.tx_hash}). Click to open the registration record.`}
    >
      On-chain ✓ #{onchain.block_number}
    </a>
  )
}

const kw = (v) => (v == null ? '—' : `${v.toFixed(2)} kW`)

function ProsumerNode({ data, selected }) {
  const role = ROLE_PILL[data.role] ?? ROLE_PILL.balanced
  return (
    <div
      className={`w-[236px] cursor-pointer rounded-2xl border-2 border-slate-300 bg-white px-3 py-2.5 text-slate-800 shadow-sm transition-shadow hover:shadow-md ${selected ? 'ring-4 ring-indigo-100' : ''}`}
      onClick={() => data.onSelect?.(data.node_id)}
      title={`${data.node_id} · simulated building, ${data.pv_kwp} kWp rooftop PV`}
    >
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <Handle id="trade-out" type="source" position={Position.Right} className="invisible" style={{ top: '35%' }} />
      <Handle id="trade-in" type="target" position={Position.Right} className="invisible" style={{ top: '65%' }} />
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: `${SOURCE_COLORS.solar}1f`, color: SOURCE_COLORS.solar }}>
          <SourceIcon type={data.profile} size={19} />
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-sm font-semibold">{nodeLabel(data.node_id)}</div>
          <div className="text-xs text-slate-500">{data.pv_kwp} kWp rooftop PV</div>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${role.cls}`}>{role.label}</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1 text-center">
        <div>
          <div className="text-[10px] uppercase text-slate-400">Solar</div>
          <div className="text-xs font-semibold" style={{ color: SOURCE_COLORS.solar }}>{kw(data.generation_kw)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-400">Load</div>
          <div className="text-xs font-semibold text-slate-700">{kw(data.consumption_kw)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-slate-400">Net</div>
          <div className="text-xs font-semibold text-slate-900">{data.net_kw == null ? '—' : `${data.net_kw > 0 ? '+' : ''}${data.net_kw.toFixed(2)} kW`}</div>
        </div>
      </div>
      <div className="mt-1.5">
        <ProvenanceBadges node={data} />
      </div>
      <div className="mt-1.5">
        <OnChainChip onchain={data.onchain} nodeId={data.node_id} />
      </div>
    </div>
  )
}

function TwinNode({ data, selected }) {
  if (data.type === 'prosumer') return <ProsumerNode data={data} selected={selected} />
  if (data.type === 'bus') return <BusNode data={data} selected={selected} />
  if (data.type === 'grid') return <GridNode data={data} />
  return <SourceNode data={data} selected={selected} />
}

export default TwinNode
