import { BaseEdge, getBezierPath } from '@xyflow/react'

// Power-flow edge: stroke width scales with the power carried (data.width),
// and a dot travels along the path in the direction of flow when data.flowing.
function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data = {} }) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const width = data.width ?? 2
  const color = data.color ?? '#94a3b8'
  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke: color, strokeWidth: width, strokeLinecap: 'round', opacity: data.flowing ? 0.85 : 0.35 }} />
      {data.flowing && (
        <circle r={Math.max(3, width * 0.7)} fill={data.dotColor ?? color}>
          <animateMotion dur={`${data.duration ?? 2.2}s`} repeatCount="indefinite" path={path} />
        </circle>
      )}
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
