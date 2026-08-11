import { Handle, Position } from '@xyflow/react'
import { healthStyle } from '../healthStatus'

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
