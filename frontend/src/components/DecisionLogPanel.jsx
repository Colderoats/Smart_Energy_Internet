const ACTION_LABELS = {
  reroute: 'Rerouted',
  isolate: 'Isolated',
  reduce_load_share: 'Curtailed',
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString()
}

function DecisionLogPanel({ decisions }) {
  return (
    <div className="flex h-full flex-col">
      <h2 className="border-b border-slate-800 px-4 py-3 text-sm font-semibold text-slate-200">
        Self-healing decision log
      </h2>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {decisions.length === 0 && (
          <p className="p-4 text-sm text-slate-400">
            No reconfigurations yet — waiting for a node to fault.
          </p>
        )}
        <ul className="divide-y divide-slate-800">
          {decisions.map((d, i) => (
            <li key={`${d.node_id}-${d.time}-${i}`} className="px-4 py-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">{d.node_id}</span>
                <span className="text-slate-500">{formatTime(d.time)}</span>
              </div>
              <div className="mt-1 text-slate-400">Trigger: {d.trigger_summary}</div>
              <div className="mt-1">
                <span className="rounded bg-sky-900 px-1.5 py-0.5 font-semibold text-sky-300">
                  {ACTION_LABELS[d.chosen_action] ?? d.chosen_action}
                </span>
                <span className="ml-1.5 text-slate-500">score {d.chosen_score}</span>
              </div>
              <div className="mt-1 text-slate-400">{d.reason}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default DecisionLogPanel
