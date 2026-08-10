import { useEffect, useState } from 'react'
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts'

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString()
}

function TimeSeriesPanel({ nodeId, latestReading }) {
  const [history, setHistory] = useState([])

  useEffect(() => {
    if (!nodeId) return
    setHistory([])
    fetch(`/nodes/${nodeId}/history?limit=100`)
      .then((res) => res.json())
      .then((data) => {
        const rows = [...data.history].reverse().map((row) => ({
          time: formatTime(row.time),
          power_output: row.power_output,
        }))
        setHistory(rows)
      })
      .catch((err) => console.error('Failed to load history', err))
  }, [nodeId])

  useEffect(() => {
    if (!latestReading || latestReading.node_id !== nodeId) return
    setHistory((prev) => [
      ...prev,
      { time: formatTime(latestReading.timestamp), power_output: latestReading.power_output },
    ])
  }, [latestReading, nodeId])

  if (!nodeId) {
    return <div className="p-4 text-sm text-slate-400">Select a node to see its history.</div>
  }

  return (
    <div className="flex h-full flex-col p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-200">{nodeId} — power output (kW)</h2>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="time" stroke="#94a3b8" fontSize={10} />
            <YAxis stroke="#94a3b8" fontSize={10} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }}
            />
            <Line type="monotone" dataKey="power_output" stroke="#38bdf8" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default TimeSeriesPanel
