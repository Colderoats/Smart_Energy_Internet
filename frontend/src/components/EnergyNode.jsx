import { Handle, Position } from '@xyflow/react'
import { SourceIcon } from '../ui/icons'
import { HEALTH_LABEL, HEALTH_TONE, SOURCE_COLORS, STATUS_COLORS, nodeLabel } from '../ui/theme'

// "live" = real sensor/API reading polled just now; "historical" = SCADA
// replay stepping through a pre-recorded dataset — CLAUDE.md's data-sourcing
// rule that the two must never be presented as the same thing. Shown as an
// always-visible badge on the node itself, not a tooltip, so the distinction
// reads at a glance without hovering.
export function SourceBadge({ sourceType }) {
  if (!sourceType) return null
  const isLive = sourceType === 'live'
  return (
    <span
      className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        isLive ? 'bg-sky-100 text-sky-700' : 'bg-purple-100 text-purple-700'
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

// Compact, icon-first node: type icon (source colour), name, output, status
// colour on the border. Full values are in the side panel on click.
function EnergyNode({ data, selected }) {
  const tone = HEALTH_TONE[data.health_status] ?? 'ok'
  const statusColor = STATUS_COLORS[tone]
  const reading = data.latest_reading
  const color = SOURCE_COLORS[data.type] ?? SOURCE_COLORS.grid

  return (
    <div
      className={`min-w-[168px] cursor-pointer rounded-2xl border-2 bg-white px-3 py-2.5 text-slate-800 shadow-sm transition-shadow hover:shadow-md ${
        selected ? 'ring-4 ring-indigo-100' : ''
      }`}
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
          <div className="text-sm text-slate-600">{reading ? `${reading.power_output.toFixed(0)} kW` : '—'}</div>
        </div>
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: statusColor }} />
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <SourceBadge sourceType={data.source_type} />
        <span className="text-[11px] text-slate-400">Updated {formatUpdated(data.last_updated)}</span>
      </div>
    </div>
  )
}

export default EnergyNode
