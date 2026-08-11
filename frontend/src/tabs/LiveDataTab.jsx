import { useCallback, useState } from 'react'
import TopologyView from '../components/TopologyView'
import TimeSeriesPanel from '../components/TimeSeriesPanel'
import { useTwinSocket } from '../hooks/useTwinSocket'
import { HEALTH_STYLES } from '../healthStatus'

// Module 1's original view, unchanged in substance — just extracted out of
// App.jsx so it can sit behind the "Live Data" tab alongside Module 2's
// separate "Digital Twin" tab.
function LiveDataTab() {
  const { nodes, edges, connected } = useTwinSocket()
  const [selectedNodeId, setSelectedNodeId] = useState('wind_01')

  const handleSelectNode = useCallback((nodeId) => setSelectedNodeId(nodeId), [])
  const selectedNode = nodes[selectedNodeId]

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2 text-xs">
        <Legend />
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
          <TopologyView
            nodes={nodes}
            edges={edges}
            onSelectNode={handleSelectNode}
            selectedNodeId={selectedNodeId}
          />
        </div>
        <div className="w-[420px] shrink-0">
          <TimeSeriesPanel nodeId={selectedNodeId} latestReading={selectedNode?.latest_reading} />
        </div>
      </div>
    </div>
  )
}

function Legend() {
  return (
    <div className="flex items-center gap-3">
      {Object.entries(HEALTH_STYLES).map(([key, style]) => (
        <span key={key} className="flex items-center gap-1">
          <span
            className="h-2.5 w-2.5 rounded-full border"
            style={{ backgroundColor: style.bg, borderColor: style.border }}
          />
          {style.label}
        </span>
      ))}
      <span className="ml-2 border-l border-slate-700 pl-3 text-slate-400">
        node_id prefixed <code className="text-slate-300">wind_scada_*</code> = replayed
        historical data
      </span>
    </div>
  )
}

export default LiveDataTab
