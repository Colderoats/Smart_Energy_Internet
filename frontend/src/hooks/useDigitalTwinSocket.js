import { useEffect, useRef, useState } from 'react'

const MAX_DECISIONS = 100

// Module 2's own hook — separate WebSocket connection from Module 1's
// useTwinSocket, and only ever reads /twin/* endpoints, so the Digital
// Twin tab never shares state with the Live Data tab.
export function useDigitalTwinSocket() {
  const [nodes, setNodes] = useState({})
  const [edges, setEdges] = useState([])
  const [decisions, setDecisions] = useState([])
  const [connected, setConnected] = useState(false)
  const socketRef = useRef(null)

  useEffect(() => {
    let cancelled = false

    fetch('/twin/nodes')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return
        const byId = {}
        for (const node of data.nodes) byId[node.node_id] = node
        setNodes(byId)
        setEdges(data.edges)
      })
      .catch((err) => console.error('Failed to load initial twin state', err))

    fetch('/twin/decisions?limit=50')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return
        setDecisions(data.decisions)
      })
      .catch((err) => console.error('Failed to load decision log', err))

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/updates`)
    socketRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'twin_node_update') {
        setNodes((prev) => ({ ...prev, [message.node.node_id]: message.node }))
      } else if (message.type === 'twin_decision') {
        setDecisions((prev) => [message.decision, ...prev].slice(0, MAX_DECISIONS))
      }
      // 'node_update' (Module 1) is ignored here on purpose.
    }

    return () => {
      cancelled = true
      ws.close()
    }
  }, [])

  return { nodes, edges, decisions, connected }
}
