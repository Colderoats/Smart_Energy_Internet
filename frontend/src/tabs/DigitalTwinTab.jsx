import { useCallback, useState } from 'react'
import DigitalTwinTopology from '../components/DigitalTwinTopology'
import DecisionLogPanel from '../components/DecisionLogPanel'
import TimeSeriesPanel from '../components/TimeSeriesPanel'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'

// Module 2 — entirely separate from LiveDataTab: its own socket hook, its
// own topology component, its own node component, and (below) its own
// decision log. Nothing here is imported from or shared with Module 1's
// view except the generic TimeSeriesPanel chart widget (parameterized to
// hit /twin/nodes/{id}/history instead of Module 1's /nodes/{id}/history).
function DigitalTwinTab() {
  const { nodes, edges, decisions, connected } = useDigitalTwinSocket()
  const [selectedNodeId, setSelectedNodeId] = useState('wind_scada_kelmarsh_1')

  const handleSelectNode = useCallback((nodeId) => setSelectedNodeId(nodeId), [])
  const selectedNode = nodes[selectedNodeId]

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2 text-xs">
        <span className="text-slate-400">
          Simulated self-healing — auto-applied to the twin's state only, no real actuation.
          Buses show current load vs. capacity; a red edge-free node is isolated.
        </span>
        <span
          className={`flex items-center gap-1.5 rounded-full px-2 py-1 ${
            connected ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'bg-emerald-400' : 'bg-red-400'}`} />
          {connected ? 'Live' : 'Disconnected'}
        </span>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 border-r border-slate-800">
          <DigitalTwinTopology
            nodes={nodes}
            edges={edges}
            onSelectNode={handleSelectNode}
            selectedNodeId={selectedNodeId}
          />
        </div>
        <div className="flex w-[420px] shrink-0 flex-col">
          <div className="h-1/2 border-b border-slate-800">
            <TimeSeriesPanel
              nodeId={selectedNodeId}
              latestReading={selectedNode?.latest_reading}
              historyUrl={`/twin/nodes/${selectedNodeId}/history?limit=100`}
            />
          </div>
          <div className="h-1/2">
            <DecisionLogPanel decisions={decisions} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default DigitalTwinTab
