import { useMemo } from 'react'
import { ReactFlow, Background, Controls } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import EnergyNode from './EnergyNode'

const nodeTypes = { energyNode: EnergyNode }

// Fixed demo layout — topology itself is static for this phase (see
// docs/architecture.md), so hand-placed positions are fine.
const POSITIONS = {
  wind_01: { x: 0, y: 0 },
  hydro_01: { x: 0, y: 100 },
  wind_scada_kelmarsh_1: { x: 0, y: 220 },
  wind_scada_kelmarsh_2: { x: 0, y: 320 },
  wind_scada_kelmarsh_3: { x: 0, y: 420 },
  wind_scada_kelmarsh_4: { x: 0, y: 520 },
  grid: { x: 320, y: 260 },
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

  const flowEdges = useMemo(
    () =>
      edges.map((edge) => ({
        id: `${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
        animated: true,
        style: { stroke: '#64748b' },
      })),
    [edges],
  )

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1e293b" gap={20} />
        <Controls />
      </ReactFlow>
    </div>
  )
}

export default TopologyView
