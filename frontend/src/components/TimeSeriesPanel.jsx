import { useEffect, useState } from 'react'
import { apiFetch } from '../auth/api'
import { CHART, nodeLabel } from '../ui/theme'
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

function TimeSeriesPanel({ nodeId, latestReading, historyUrl, color }) {
  const [history, setHistory] = useState([])

  useEffect(() => {
    if (!nodeId) return
    setHistory([])
    apiFetch(historyUrl ?? `/nodes/${nodeId}/history?limit=100`)
      .then((res) => res.json())
      .then((data) => {
        const rows = [...data.history].reverse().map((row) => ({
          time: formatTime(row.time),
          power_output: row.power_output,
        }))
        setHistory(rows)
      })
      .catch((err) => console.error('Failed to load history', err))
  }, [nodeId, historyUrl])

  useEffect(() => {
    if (!latestReading || latestReading.node_id !== nodeId) return
    setHistory((prev) => [
      ...prev,
      { time: formatTime(latestReading.timestamp), power_output: latestReading.power_output },
    ])
  }, [latestReading, nodeId])

  if (!nodeId) {
    return <div className="p-4 text-sm text-slate-500">Select a node to see its history.</div>
  }

  return (
    <div className="flex h-full flex-col">
      <h2 className="mb-2 text-sm font-semibold text-slate-700" title={nodeId}>
        {nodeLabel(nodeId)} — power output (kW)
      </h2>
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="time" stroke={CHART.axis} fontSize={11} tickLine={false} minTickGap={30} />
            <YAxis stroke={CHART.axis} fontSize={11} tickLine={false} axisLine={false} width={48} />
            <Tooltip {...CHART.tooltip} />
            <Line type="monotone" dataKey="power_output" stroke={color ?? '#4f46e5'} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default TimeSeriesPanel
