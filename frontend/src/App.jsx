import { useState } from 'react'
import LiveDataTab from './tabs/LiveDataTab'
import DigitalTwinTab from './tabs/DigitalTwinTab'

const TABS = [
  { id: 'live', label: 'Live Data' },
  { id: 'twin', label: 'Digital Twin' },
]

function App() {
  const [tab, setTab] = useState('live')

  return (
    <div className="flex h-svh flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div>
          <h1 className="text-lg font-semibold">Smart Energy Internet</h1>
          <p className="text-xs text-slate-400">
            Live wind/hydro + replayed SCADA data, and the digital twin's self-healing response
          </p>
        </div>
        <nav className="flex gap-1 rounded-lg bg-slate-900 p-1 text-sm">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
                tab === t.id ? 'bg-sky-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {/* Only one tab is ever mounted at a time — they don't share state or
          a socket connection, per the requirement that these be genuinely
          separate views, not one graph with extra info bolted on. */}
      {tab === 'live' ? <LiveDataTab /> : <DigitalTwinTab />}
    </div>
  )
}

export default App
