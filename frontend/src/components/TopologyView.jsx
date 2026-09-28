import { useMemo } from 'react'
import { ReactFlow, Background, Controls } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import EnergyNode from './EnergyNode'
import FlowEdge, { flowWidth } from './FlowEdge'
import { SOURCE_COLORS } from '../ui/theme'

const nodeTypes = { energyNode: EnergyNode }
const edgeTypes = { flow: FlowEdge }

// Fixed demo layout — topology itself is static for this phase (see
// docs/architecture.md), so hand-placed positions are fine.
const POSITIONS = {
  wind_01: { x: 0, y: 0 },
  hydro_01: { x: 0, y: 100 },
  wind_scada_kelmarsh_1: { x: 0, y: 220 },
  wind_scada_kelmarsh_2: { x: 0, y: 320 },
  wind_scada_kelmarsh_3: { x: 0, y: 420 },
  wind_scada_kelmarsh_4: { x: 0, y: 520 },
  grid: { x: 360, y: 260 },
}

function TopologyView({ nodes, edges, onSelectNode, selectedNodeId }) {
  const flowNodes = useMemo(
    () =>
      Object.values(nodes).map((node) => ({
        id: node.node_id,
        type: 'energyNode',
        position: POSITIONS[node.node_id] ?? { x: 0, y: 0 },
        data: { ...node, onSelect: onSelectNode },
        selected: node.node_id === selectedNodeId,
      })),
    [nodes, onSelectNode, selectedNodeId],
  )

  // Edge thickness = the source's latest power output; a dot travels
  // source -> grid while it is producing.
  const flowEdges = useMemo(() => {
    const kwOf = (id) => nodes[id]?.latest_reading?.power_output ?? 0
    const maxKw = Math.max(1, ...edges.map((e) => kwOf(e.source)))
    return edges.map((edge) => {
      const kw = kwOf(edge.source)
      const color = SOURCE_COLORS[nodes[edge.source]?.type] ?? SOURCE_COLORS.grid
      return {
        id: `${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        type: 'flow',
        data: { width: flowWidth(kw, maxKw), color, dotColor: color, flowing: kw > 0 },
      }
    })
  }, [edges, nodes])

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

export default TopologyView
