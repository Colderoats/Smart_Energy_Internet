import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../auth/api'
import { openAuthedSocket } from '../auth/socket'

export function useTwinSocket() {
  const [nodes, setNodes] = useState({})
  const [edges, setEdges] = useState([])
  const [connected, setConnected] = useState(false)
  const socketRef = useRef(null)

  useEffect(() => {
    let cancelled = false

    apiFetch('/nodes')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return
        const byId = {}
        for (const node of data.nodes) byId[node.node_id] = node
        setNodes(byId)
        setEdges(data.edges)
      })
      .catch((err) => console.error('Failed to load initial node state', err))

    // Authenticated socket: refreshes + reconnects on 4401 (token expiry).
    const ws = openAuthedSocket({
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onMessage: (message) => {
        if (message.type === 'node_update') {
          setNodes((prev) => ({ ...prev, [message.node.node_id]: message.node }))
        }
      },
    })
    socketRef.current = ws

    return () => {
      cancelled = true
      ws.close()
    }
  }, [])

  return { nodes, edges, connected }
}
