import logging

from fastapi import WebSocket

logger = logging.getLogger("sei")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, bool] = {}  # ws -> market_only

    async def connect(self, ws: WebSocket, market_only: bool = False) -> None:
        """market_only (prosumer sessions): the socket only ever receives market_* messages."""
        await ws.accept()
        self._connections[ws] = market_only

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    async def broadcast(self, message: dict) -> None:
        dead = []
        is_market = str(message.get("type", "")).startswith("market_")
        for ws, market_only in list(self._connections.items()):
            if market_only and not is_market:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
