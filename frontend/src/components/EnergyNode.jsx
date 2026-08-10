import { Handle, Position } from '@xyflow/react'
import { healthStyle } from '../healthStatus'

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
      <div className="font-semibold">{data.node_id}</div>
      <div className="opacity-80">
        {data.type} · {data.source_type ?? 'structural'}
      </div>
      {reading && (
        <div className="mt-1 opacity-90">{reading.power_output.toFixed(1)} kW</div>
      )}
      <div className="mt-1 text-[10px] uppercase tracking-wide opacity-80">{style.label}</div>
    </div>
  )
}

export default EnergyNode
