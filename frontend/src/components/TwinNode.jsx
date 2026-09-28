import { Handle, Position } from '@xyflow/react'
import { healthStyle } from '../healthStatus'

// Module 3: which detector said what. Rule-based (Module 2) and TA-GNN run side
// by side; `flagged_by` says which one(s) raised the current flag. TA-GNN output
// is a forecast on REPLAYED SCADA data, and the rule-based "fault" on replayed
// nodes is usually the replayed status-log label, not a statistic.
function DetectorRows({ data }) {
  const detectors = data.detectors
  if (!detectors) return null
  const rule = detectors.rule_based
  const gnn = detectors.ta_gnn
  const flaggedBy = data.flagged_by ?? []
  const fromLabel = rule?.basis === 'replayed_ground_truth_label'

  return (
    <div className="mt-2 space-y-1 rounded bg-black/30 px-1.5 py-1 text-[10px]">
      {flaggedBy.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {flaggedBy.includes('ta_gnn') && (
            <span className="rounded bg-violet-600 px-1 py-0.5 font-semibold uppercase">Flagged: TA-GNN</span>
          )}
          {flaggedBy.includes('rule_based') && (
            <span className="rounded bg-slate-600 px-1 py-0.5 font-semibold uppercase">Flagged: rule-based</span>
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
          <span className="opacity-70">Rule-based</span>
          <span className={rule.flagged ? 'font-semibold text-amber-300' : 'opacity-80'}>
            {rule.flagged ? (fromLabel ? 'FAULT (replayed label)' : 'FLAG') : 'clear'}
          </span>
        </div>
      )}
      {gnn && (
        <div
          className="flex justify-between gap-2"
          title={`${gnn.model}: probability that a fault starts within ${gnn.horizon_min} min. Forecast on replayed SCADA data, not sensed.`}
        >
          <span className="opacity-70">TA-GNN</span>
          <span className={gnn.flagged ? 'font-semibold text-violet-300' : 'opacity-80'}>
            {gnn.flagged
              ? `FLAG ${(gnn.probability * 100).toFixed(0)}% ≤${gnn.horizon_min}min`
              : `${(gnn.probability * 100).toFixed(1)}%`}
          </span>
        </div>
      )}
    </div>
  )
}

function SourceNode({ data }) {
  const style = healthStyle(data.health_status)
  const reading = data.latest_reading
  const curtailed = data.load_share < 1

  return (
    <div
      className="min-w-[160px] cursor-pointer rounded-lg border-2 px-3 py-2 text-xs text-white shadow-md"
      style={{ backgroundColor: style.bg, borderColor: style.border }}
      onClick={() => data.onSelect?.(data.node_id)}
    >
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <div className="font-semibold">{data.node_id}</div>
      <div className="opacity-80">
        {data.type} · {data.source_type}
      </div>
      {reading && <div className="mt-1 opacity-90">{reading.power_output.toFixed(1)} kW</div>}
      <div className="mt-1 text-[10px] uppercase tracking-wide opacity-80">{style.label}</div>
      <DetectorRows data={data} />
      {data.isolated && (
        <div className="mt-1 rounded bg-black/30 px-1 py-0.5 text-[10px] font-semibold uppercase">
          Isolated — no route to grid
        </div>
      )}
      {!data.isolated && curtailed && (
        <div className="mt-1 rounded bg-black/30 px-1 py-0.5 text-[10px] font-semibold uppercase">
          Curtailed to {Math.round(data.load_share * 100)}%
        </div>
      )}
      {!data.isolated && (
        <div className="mt-1 text-[10px] opacity-70">via {data.active_connection}</div>
      )}
    </div>
  )
}

function BusNode({ data }) {
  const overloaded = data.current_load_kw > data.capacity_kw
  const pct = Math.min(100, (data.current_load_kw / data.capacity_kw) * 100)

  return (
    <div
      className={`min-w-[150px] rounded-lg border-2 bg-slate-800 px-3 py-2 text-xs text-white shadow-md ${
        overloaded ? 'border-red-500' : 'border-slate-500'
      }`}
    >
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <div className="font-semibold">{data.node_id}</div>
      <div className="mt-1 opacity-80">
        {data.current_load_kw.toFixed(0)} / {data.capacity_kw.toFixed(0)} kW
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-700">
        <div
          className={`h-full ${overloaded ? 'bg-red-500' : 'bg-sky-400'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {overloaded && (
        <div className="mt-1 text-[10px] font-semibold uppercase text-red-400">Overloaded</div>
      )}
    </div>
  )
}

function GridNode({ data }) {
  return (
    <div className="min-w-[110px] rounded-lg border-2 border-emerald-500 bg-emerald-950 px-3 py-2 text-xs font-semibold text-emerald-200 shadow-md">
      <Handle type="target" position={Position.Left} className="invisible" />
      {data.node_id.toUpperCase()}
    </div>
  )
}

function TwinNode({ data }) {
  if (data.type === 'bus') return <BusNode data={data} />
  if (data.type === 'grid') return <GridNode data={data} />
  return <SourceNode data={data} />
}

export default TwinNode
