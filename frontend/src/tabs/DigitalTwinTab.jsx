import { useCallback, useState } from 'react'
import DigitalTwinTopology from '../components/DigitalTwinTopology'
import DecisionLogPanel from '../components/DecisionLogPanel'
import TimeSeriesPanel from '../components/TimeSeriesPanel'
import NodeSidePanel from '../components/NodeSidePanel'
import { useDigitalTwinSocket } from '../hooks/useDigitalTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import { SOURCE_COLORS } from '../ui/theme'
import { Legend } from './LiveDataTab'

// Module 2 — entirely separate from LiveDataTab: its own socket hook, its
// own topology component, its own node component, and its own decision log.
// Shown as the Grid Map's "Digital Twin" view. Shared with the Live View:
// only the generic TimeSeriesPanel chart (parameterized to hit
// /twin/nodes/{id}/history) and presentation pieces (legend, side panel).
function DigitalTwinTab() {
  const { nodes, decisions, connected } = useDigitalTwinSocket()
  useReportConnection(connected)
  const [selectedNodeId, setSelectedNodeId] = useState('wind_scada_kelmarsh_1')

  const handleSelectNode = useCallback((nodeId) => setSelectedNodeId(nodeId), [])
  const selectedNode = nodes[selectedNodeId]
  const isSource = selectedNode && selectedNode.type !== 'bus' && selectedNode.type !== 'grid'

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <p className="text-sm text-slate-500">
        Simulated self-healing: auto-applied to the twin's state only, no real actuation. TA-GNN predictions are forecasts
        on replayed Kelmarsh SCADA data, not sensed values.
      </p>
      <div className="flex min-h-0 flex-1 gap-4">
        <div className="relative min-w-0 flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white">
          <DigitalTwinTopology nodes={nodes} onSelectNode={handleSelectNode} selectedNodeId={selectedNodeId} />
          <Legend />
        </div>
        <aside className="flex w-[360px] shrink-0 flex-col gap-4 overflow-y-auto">
          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <NodeSidePanel node={selectedNode} twin />
          </div>
          {isSource && (
            <div className="h-56 shrink-0 rounded-2xl border border-slate-200 bg-white p-4">
              <TimeSeriesPanel
                nodeId={selectedNodeId}
                latestReading={selectedNode?.latest_reading}
                historyUrl={`/twin/nodes/${selectedNodeId}/history?limit=100`}
                color={SOURCE_COLORS[selectedNode?.type]}
              />
            </div>
          )}
          <div className="h-80 shrink-0 overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <DecisionLogPanel decisions={decisions} />
          </div>
        </aside>
      </div>
    </div>
  )
}

export default DigitalTwinTab
