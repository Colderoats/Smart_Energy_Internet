import { useCallback, useState } from 'react'
import TopologyView from '../components/TopologyView'
import TimeSeriesPanel from '../components/TimeSeriesPanel'
import NodeSidePanel from '../components/NodeSidePanel'
import { useTwinSocket } from '../hooks/useTwinSocket'
import { useReportConnection } from '../ui/AppShell'
import { Details } from '../ui/components'
import { STATUS_COLORS, SOURCE_COLORS } from '../ui/theme'

// Module 1's original view (own hook, own socket, own topology), now the
// Grid Map's "Live View". Same data; presentation only.
function LiveDataTab() {
  const { nodes, edges, connected } = useTwinSocket()
  useReportConnection(connected)
  const [selectedNodeId, setSelectedNodeId] = useState('wind_01')

  const handleSelectNode = useCallback((nodeId) => setSelectedNodeId(nodeId), [])
  const selectedNode = nodes[selectedNodeId]

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="relative min-w-0 flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <TopologyView nodes={nodes} edges={edges} onSelectNode={handleSelectNode} selectedNodeId={selectedNodeId} />
        <Legend />
      </div>
      <aside className="flex w-[360px] shrink-0 flex-col gap-4 overflow-y-auto">
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <NodeSidePanel node={selectedNode} />
        </div>
        {selectedNode && selectedNode.type !== 'grid' && (
          <div className="h-64 shrink-0 rounded-2xl border border-slate-200 bg-white p-4">
            <TimeSeriesPanel
              nodeId={selectedNodeId}
              latestReading={selectedNode?.latest_reading}
              color={SOURCE_COLORS[selectedNode?.type]}
            />
          </div>
        )}
      </aside>
    </div>
  )
}

export function Legend() {
  return (
    <div className="absolute right-3 top-3 z-10 rounded-xl border border-slate-200 bg-white/95 px-3 py-2 text-xs text-slate-600 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        {[
          ['Normal', STATUS_COLORS.ok],
          ['Warning / predicted', STATUS_COLORS.warn],
          ['Fault', STATUS_COLORS.bad],
        ].map(([l, c]) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            {l}
          </span>
        ))}
      </div>
      <div className="mt-1.5">
        <Details label="What am I looking at?">
          <p className="max-w-xs text-slate-500">
            Line thickness = power carried; the moving dot shows direction of flow. "Replayed" nodes (Kelmarsh T1–T4,
            ids <code>wind_scada_*</code>) are historical SCADA data replayed at a fixed interval, not live.
          </p>
        </Details>
      </div>
    </div>
  )
}

export default LiveDataTab
