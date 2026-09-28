import { notifyAuthExpired, refreshSession } from './api'

// Opens /ws/updates with the session cookie. The backend closes with
// 4401 when the access token is missing/expired (including when it expires
// mid-connection) and 4403 for a foreign origin. On 4401 we refresh the
// session once and reconnect; other unexpected closes reconnect with backoff.
export function openAuthedSocket({ onOpen, onClose, onMessage }) {
  let ws = null
  let closedByUs = false
  let retryTimer = null
  let attempts = 0
  let openedAt = 0
  let quickAuthRejects = 0

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${protocol}://${window.location.host}/ws/updates`)
    ws.onopen = () => {
      openedAt = Date.now()
      onOpen?.()
    }
    ws.onmessage = (event) => {
      attempts = 0
      quickAuthRejects = 0
      let message
      try {
        message = JSON.parse(event.data)
      } catch {
        return
      }
      onMessage(message)
    }
    ws.onclose = async (event) => {
      onClose?.()
      if (closedByUs || event.code === 4403) return
      if (event.code === 4401) {
        // Rejected right after connecting several times: the refresh is not
        // helping, so stop looping and treat the session as gone.
        quickAuthRejects = Date.now() - openedAt < 5000 ? quickAuthRejects + 1 : 0
        if (quickAuthRejects > 2) {
          notifyAuthExpired()
          return
        }
        const ok = await refreshSession()
        if (closedByUs) return
        if (!ok) {
          notifyAuthExpired()
          return
        }
        connect()
        return
      }
      const delay = Math.min(30000, 1000 * 2 ** attempts)
      attempts += 1
      retryTimer = setTimeout(connect, delay)
    }
  }

  connect()

  return {
    close() {
      closedByUs = true
      clearTimeout(retryTimer)
      ws?.close()
    },
  }
}
