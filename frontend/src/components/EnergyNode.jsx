import { Handle, Position } from '@xyflow/react'
import { healthStyle } from '../healthStatus'

// "live" = real sensor/API reading polled just now; "historical" = SCADA
// replay stepping through a pre-recorded dataset — CLAUDE.md's data-sourcing
// rule that the two must never be presented as the same thing. Shown as an
// always-visible badge on the node itself, not a tooltip, so the distinction
// reads at a glance without hovering.
function SourceBadge({ sourceType }) {
  if (!sourceType) return null
  const isLive = sourceType === 'live'
  return (
    <span
      className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
        isLive ? 'bg-sky-400 text-sky-950' : 'bg-purple-300 text-purple-950'
      }`}
    >
      {isLive ? 'Live' : 'Replayed'}
    </span>
  )
}

function formatUpdated(iso) {
  if (!iso) return 'no data yet'
  return new Date(iso).toLocaleTimeString()
}

function EnergyNode({ data }) {
  const style = healthStyle(data.health_status)
  const reading = data.latest_reading

  return (
    <div
      className="rounded-lg border-2 px-3 py-2 text-xs text-white shadow-md min-w-[140px] cursor-pointer"
      style={{ backgroundColor: style.bg, borderColor: style.border }}
      onClick={() => data.onSelect?.(data.node_id)}
    >
      <Handle type="target" position={Position.Left} className="invisible" />
      <Handle type="source" position={Position.Right} className="invisible" />
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold">{data.node_id}</div>
        <SourceBadge sourceType={data.source_type} />
      </div>
      <div className="opacity-80">
        {data.type} · {data.source_type ?? 'structural'}
      </div>
      {reading && (
        <div className="mt-1 opacity-90">{reading.power_output.toFixed(1)} kW</div>
      )}
      <div className="mt-1 text-[10px] uppercase tracking-wide opacity-80">{style.label}</div>
      <div className="mt-1 text-[10px] opacity-60">Updated {formatUpdated(data.last_updated)}</div>
    </div>
  )
}

export default EnergyNode
