import { useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, Background, Controls } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import TwinNode from './TwinNode'
import FlowEdge, { flowWidth } from './FlowEdge'
import { SOURCE_COLORS } from '../ui/theme'

const nodeTypes = { twinNode: TwinNode }
const edgeTypes = { flow: FlowEdge }

// How long a just-changed edge stays visibly highlighted after a
// reroute/isolate, so the reconfiguration reads as an event, not a silent
// state update.
const HIGHLIGHT_MS = 2500

// Fixed demo layout, same spirit as Module 1's TopologyView — sources on
// the left, the two collector buses in the middle (this is where reroutes
// visibly swing an edge from one column to the other), grid on the right.
const POSITIONS = {
  // Compact icon cards (UI redesign) — tighter spacing than the Module 3
  // detector-row cards, which now live in the side panel instead.
  wind_01: { x: 0, y: 0 },
  hydro_01: { x: 0, y: 100 },
  wind_scada_kelmarsh_1: { x: 0, y: 200 },
  wind_scada_kelmarsh_2: { x: 0, y: 300 },
  wind_scada_kelmarsh_3: { x: 0, y: 400 },
  wind_scada_kelmarsh_4: { x: 0, y: 500 },
  bus_a: { x: 330, y: 120 },
  bus_b: { x: 330, y: 390 },
  grid: { x: 630, y: 260 },
}

function DigitalTwinTopology({ nodes, onSelectNode, selectedNodeId }) {
  const flowNodes = useMemo(
    () =>
      Object.values(nodes).map((node) => ({
        id: node.node_id,
        type: 'twinNode',
        position: POSITIONS[node.node_id] ?? { x: 0, y: 0 },
        data: { ...node, onSelect: onSelectNode },
        selected: node.node_id === selectedNodeId,
      })),
    [nodes, onSelectNode, selectedNodeId],
  )

  // The routing edges are derived live from each source node's
  // active_connection/isolated state (not a one-time snapshot) — this is
  // the actual current topology, and it's what makes a self-healing
  // reroute/isolate visibly move the line on the graph instead of leaving
  // it pointing at the node's original bus forever.
  const sourceEdges = useMemo(
    () =>
      Object.values(nodes)
        .filter((node) => node.type !== 'bus' && node.type !== 'grid' && !node.isolated && node.active_connection)
        .map((node) => ({
          id: `${node.node_id}-${node.active_connection}`,
          source: node.node_id,
          target: node.active_connection,
          // Twin estimate of power on this line: latest output x load share.
          kw: (node.latest_reading?.power_output ?? 0) * (node.load_share ?? 1),
          color: SOURCE_COLORS[node.type] ?? SOURCE_COLORS.grid,
        })),
    [nodes],
  )

  // bus_a -> grid / bus_b -> grid are structural and never reconfigured by
  // self-healing, so they're safe to keep constant.
  const busEdges = useMemo(
    () =>
      Object.values(nodes)
        .filter((node) => node.type === 'bus')
        .map((node) => ({
          id: `${node.node_id}-grid`,
          source: node.node_id,
          target: 'grid',
          kw: node.current_load_kw ?? 0,
          color: SOURCE_COLORS.grid,
        })),
    [nodes],
  )

  const highlightedEdgeIds = useRecentlyChangedEdges(sourceEdges)

  const flowEdges = useMemo(() => {
    const all = [...sourceEdges, ...busEdges]
    const maxKw = Math.max(1, ...all.map((e) => e.kw))
    return all.map(({ kw, color, ...edge }) => {
      const highlighted = highlightedEdgeIds.has(edge.id)
      return {
        ...edge,
        type: 'flow',
        data: {
          width: highlighted ? Math.max(4, flowWidth(kw, maxKw)) : flowWidth(kw, maxKw),
          color: highlighted ? '#f97316' : color,
          dotColor: highlighted ? '#f97316' : color,
          flowing: kw > 0,
        },
      }
    })
  }, [sourceEdges, busEdges, highlightedEdgeIds])

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#e2e8f0" gap={22} />
        <Controls />
      </ReactFlow>
    </div>
  )
}

// Tracks each source node's active_connection across renders and returns
// the set of edge ids that just swung to a different target (a reroute) so
// the graph can flash that edge briefly instead of silently updating it.
function useRecentlyChangedEdges(sourceEdges) {
  const prevTargetsRef = useRef({})
  const timersRef = useRef({})
  const [highlighted, setHighlighted] = useState(() => new Set())

  useEffect(() => {
    const prevTargets = prevTargetsRef.current
    const changedIds = sourceEdges
      .filter((edge) => {
        const prevTarget = prevTargets[edge.source]
        return prevTarget !== undefined && prevTarget !== edge.target
      })
      .map((edge) => edge.id)

    if (changedIds.length > 0) {
      setHighlighted((current) => new Set([...current, ...changedIds]))
      for (const id of changedIds) {
        clearTimeout(timersRef.current[id])
        timersRef.current[id] = setTimeout(() => {
          setHighlighted((current) => {
            const next = new Set(current)
            next.delete(id)
            return next
          })
        }, HIGHLIGHT_MS)
      }
    }

    prevTargetsRef.current = Object.fromEntries(sourceEdges.map((edge) => [edge.source, edge.target]))
  }, [sourceEdges])

  useEffect(
    () => () => {
      for (const timer of Object.values(timersRef.current)) clearTimeout(timer)
    },
    [],
  )

  return highlighted
}

export default DigitalTwinTopology
