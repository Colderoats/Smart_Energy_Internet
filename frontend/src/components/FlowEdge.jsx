import { BaseEdge, EdgeLabelRenderer, getBezierPath } from '@xyflow/react'

// Power-flow edge: stroke width scales with the power carried (data.width),
// and a dot travels along the path in the direction of flow when data.flowing.
function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data = {} }) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const width = data.width ?? 2
  const color = data.color ?? '#94a3b8'
  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: width, strokeLinecap: 'round', opacity: data.flowing ? 0.85 : data.label ? 0.7 : 0.35 }} />
      {data.flowing && (
        <circle r={Math.max(3, width * 0.7)} fill={data.dotColor ?? color}>
          {/* data.reverse: the dot travels target -> source (e.g. community bus -> a deficit prosumer) */}
          <animateMotion dur={`${data.duration ?? 2.2}s`} repeatCount="indefinite" path={path} {...(data.reverse ? { keyPoints: '1;0', keyTimes: '0;1', calcMode: 'linear' } : {})} />
        </circle>
      )}
      {data.label && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded-md bg-white/90 px-1.5 py-0.5 text-[10px] font-medium text-slate-500"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

// Prosumer-market trade edge: seller -> buyer, drawn as a bow to the right of the prosumer
// column (both ends sit on the cards' right side). Violet = blockchain. Dashed with a moving
// dot while the interval runs (data.settled false); solid once settled on chain. data.grid draws
// the thin grey "served by grid" edge instead (not on-chain).
export function TradeEdge({ id, sourceX, sourceY, targetX, targetY, data = {} }) {
  const bow = 70 + (data.lane ?? 0) * 18
  const path = `M ${sourceX} ${sourceY} C ${sourceX + bow} ${sourceY}, ${targetX + bow} ${targetY}, ${targetX} ${targetY}`
  // The bow's apex sits ~0.75 * bow to the right of the cards; the label starts just right of it so the cards never cover it.
  const midX = Math.max(sourceX, targetX) + bow * 0.75 + 10
  const midY = (sourceY + targetY) / 2
  const color = data.grid ? '#94a3b8' : '#7c3aed'
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={{ stroke: color, strokeWidth: data.grid ? 1.5 : 3, strokeDasharray: data.settled || data.grid ? undefined : '7 5', strokeLinecap: 'round', opacity: data.grid ? 0.7 : 0.95 }}
      />
      {!data.grid && !data.settled && (
        <circle r={4} fill={color}>
          <animateMotion dur="2s" repeatCount="indefinite" path={path} />
        </circle>
      )}
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan pointer-events-none absolute rounded-md border bg-white px-1.5 py-0.5 text-[11px] font-medium shadow-sm"
          style={{ transform: `translate(0, -50%) translate(${midX}px, ${midY}px)`, borderColor: color, color }}
        >
          {data.label}
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

// Maps a power value to a stroke width between 1.5 and 8 px.
// eslint-disable-next-line react-refresh/only-export-components
export function flowWidth(kw, maxKw) {
  if (!maxKw || !kw || kw <= 0) return 1.5
  return 1.5 + 6.5 * Math.min(1, kw / maxKw)
}

export default FlowEdge
