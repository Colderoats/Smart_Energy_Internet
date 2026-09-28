import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../auth/api'
import { openAuthedSocket } from '../auth/socket'

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

    apiFetch('/twin/nodes')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return
        const byId = {}
        for (const node of data.nodes) byId[node.node_id] = node
        setNodes(byId)
        setEdges(data.edges)
      })
      .catch((err) => console.error('Failed to load initial twin state', err))

    apiFetch('/twin/decisions?limit=50')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return
        setDecisions(data.decisions)
      })
      .catch((err) => console.error('Failed to load decision log', err))

    // Authenticated socket: refreshes + reconnects on 4401 (token expiry).
    const ws = openAuthedSocket({
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onMessage: (message) => {
        if (message.type === 'twin_node_update') {
          setNodes((prev) => ({ ...prev, [message.node.node_id]: message.node }))
        } else if (message.type === 'twin_decision') {
          setDecisions((prev) => [message.decision, ...prev].slice(0, MAX_DECISIONS))
        }
        // 'node_update' (Module 1) is ignored here on purpose.
      },
    })
    socketRef.current = ws

    return () => {
      cancelled = true
      ws.close()
    }
  }, [])

  return { nodes, edges, decisions, connected }
}
