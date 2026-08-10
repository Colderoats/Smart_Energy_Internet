import { useEffect, useRef, useState } from 'react'

export function useTwinSocket() {
  const [nodes, setNodes] = useState({})
  const [edges, setEdges] = useState([])
  const [connected, setConnected] = useState(false)
  const socketRef = useRef(null)

  useEffect(() => {
    let cancelled = false

    fetch('/nodes')
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return
        const byId = {}
        for (const node of data.nodes) byId[node.node_id] = node
        setNodes(byId)
        setEdges(data.edges)
      })
      .catch((err) => console.error('Failed to load initial node state', err))

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/updates`)
    socketRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'node_update') {
        setNodes((prev) => ({ ...prev, [message.node.node_id]: message.node }))
      }
    }

    return () => {
      cancelled = true
      ws.close()
    }
  }, [])

  return { nodes, edges, connected }
}
