import { useState } from 'react'
import LiveDataTab from './LiveDataTab'
import DigitalTwinTab from './DigitalTwinTab'
import FederatedPanel from '../components/FederatedPanel'
import { Segmented, Tabs } from '../ui/components'

// Grid Map: "Topology" (Live View = Module 1's view, Digital Twin = Module 2's
// view — separate, non-overlapping toggles; only one is mounted at a time,
// each with its own hook and socket) and "Federated Learning".
export default function GridMapTab({ search }) {
  const params = new URLSearchParams(search)
  const [tab, setTab] = useState(params.get('tab') === 'fl' ? 'fl' : 'topology')
  const [view, setView] = useState(params.get('view') === 'twin' ? 'twin' : 'live')

  return (
    <div className={`flex flex-col gap-4 p-6 ${tab === 'topology' ? 'h-full' : ''}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { id: 'topology', label: 'Topology' },
            { id: 'fl', label: 'Federated Learning' },
          ]}
          value={tab}
          onChange={setTab}
        />
        {tab === 'topology' && (
          <Segmented
            options={[
              { id: 'live', label: 'Live View' },
              { id: 'twin', label: 'Digital Twin' },
            ]}
            value={view}
            onChange={setView}
          />
        )}
      </div>
      {tab === 'topology' && view === 'live' && <LiveDataTab />}
      {tab === 'topology' && view === 'twin' && <DigitalTwinTab />}
      {tab === 'fl' && <FederatedPanel />}
    </div>
  )
}
