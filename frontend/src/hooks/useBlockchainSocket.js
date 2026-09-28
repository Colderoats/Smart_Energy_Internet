import { useCallback, useEffect, useRef, useState } from 'react'

const PAGE_SIZE = 50

// Module 5's own hook — same pattern as useDigitalTwinSocket: one initial
// fetch, then push-only updates over /ws/updates (chain_record /
// chain_status messages). No polling. Records are kept in a map by id so a
// status change (Pending -> Confirmed) updates the existing row in place.
export function useBlockchainSocket(eventType) {
  const [status, setStatus] = useState(null)
  const [records, setRecords] = useState({})
  const [total, setTotal] = useState(0)
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const knownIds = useRef(new Set())

  const fetchStatus = useCallback(() => {
    return fetch('/chain/status')
      .then((res) => res.json())
      .then(setStatus)
      .catch((err) => console.error('Failed to load chain status', err))
  }, [])

  const fetchPage = useCallback(
    (offset) => {
      const qs = new URLSearchParams({ limit: PAGE_SIZE, offset })
      if (eventType) qs.set('event_type', eventType)
      return fetch(`/chain/records?${qs}`)
        .then(async (res) => {
          const data = await res.json()
          if (!res.ok) throw new Error(data.detail || res.statusText)
          return data
        })
        .then((data) => {
          setLoadError(null)
          setTotal(data.total)
          setRecords((prev) => {
            const next = offset === 0 ? {} : { ...prev }
            if (offset === 0) knownIds.current = new Set()
            for (const r of data.records) {
              next[r.id] = r
              knownIds.current.add(r.id)
            }
            return next
          })
        })
        .catch((err) => setLoadError(err.message))
    },
    [eventType],
  )

  useEffect(() => {
    fetchPage(0)
  }, [fetchPage])

  useEffect(() => {
    fetchStatus()
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/updates`)
    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === 'chain_record') {
        const r = message.record
        if (!knownIds.current.has(r.id)) {
          knownIds.current.add(r.id)
          if (!eventType || r.event_type === eventType) setTotal((t) => t + 1)
        }
        setRecords((prev) => ({ ...prev, [r.id]: r }))
        setLastMessage(r)
      } else if (message.type === 'chain_status') {
        setStatus(message.status)
      }
      // node_update / twin_* messages are ignored here on purpose.
    }
    return () => ws.close()
  }, [fetchStatus, eventType])

  const list = Object.values(records)
    .filter((r) => !eventType || r.event_type === eventType)
    .sort((a, b) => b.id - a.id)

  return {
    status,
    records: list,
    total,
    connected,
    lastMessage,
    loadError,
    refreshStatus: fetchStatus,
    loadMore: () => fetchPage(list.length),
    hasMore: list.length < total,
  }
}
