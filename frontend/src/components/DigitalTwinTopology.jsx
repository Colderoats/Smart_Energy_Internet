import { useMemo } from 'react'
import { ReactFlow, Background, Controls } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import TwinNode from './TwinNode'

const nodeTypes = { twinNode: TwinNode }

// Fixed demo layout, same spirit as Module 1's TopologyView — sources on
// the left, the two collector buses in the middle (this is where reroutes
// visibly swing an edge from one column to the other), grid on the right.
const POSITIONS = {
  wind_01: { x: 0, y: 0 },
  hydro_01: { x: 0, y: 100 },
  wind_scada_kelmarsh_1: { x: 0, y: 220 },
  wind_scada_kelmarsh_2: { x: 0, y: 340 },
  wind_scada_kelmarsh_3: { x: 0, y: 460 },
  wind_scada_kelmarsh_4: { x: 0, y: 580 },
  bus_a: { x: 340, y: 130 },
  bus_b: { x: 340, y: 430 },
  grid: { x: 620, y: 280 },
}

function DigitalTwinTopology({ nodes, edges, onSelectNode, selectedNodeId }) {
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

export default DigitalTwinTopology
