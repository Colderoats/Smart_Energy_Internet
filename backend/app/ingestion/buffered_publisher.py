"""Store-and-forward wrapper for the sensor -> MQTT publish step (Set-2 TC02).

The product has no MQTT path yet (ESP32 -> Mosquitto is a documented seam, see models/reading.py), so this is transport-agnostic:
`send` is whatever really publishes (e.g. a paho-mqtt client's publish) and must raise ConnectionError / OSError / TimeoutError when
the broker is unreachable. While it does, messages are kept in a bounded FIFO buffer (oldest dropped first, and counted) and are
re-sent in their original order on the next publish() or flush(). Nothing imports this module yet.
"""

import logging
from collections import deque
from typing import Callable

logger = logging.getLogger("sei")

_BROKER_DOWN = (ConnectionError, OSError, TimeoutError)


class BufferedPublisher:
    def __init__(self, send: Callable[[str, bytes], None], max_buffered: int = 1000):
        self._send = send
        self._buffer: deque[tuple[str, bytes]] = deque()
        self._max = max_buffered
        self.dropped = 0

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    def publish(self, topic: str, payload: bytes) -> bool:
        """True if the message (and everything buffered before it) reached the broker; False if it is buffered for a later retry."""
        if len(self._buffer) >= self._max:
            self._buffer.popleft()
            self.dropped += 1
            logger.warning("Publish buffer full (%d): oldest message dropped", self._max)
        self._buffer.append((topic, payload))
        return self.flush()

    def flush(self) -> bool:
        """Re-send buffered messages oldest first; stops at the first failure and keeps that message for the next attempt."""
        while self._buffer:
            topic, payload = self._buffer[0]
            try:
                self._send(topic, payload)
            except _BROKER_DOWN as exc:
                logger.warning("Broker unreachable (%s): %d message(s) buffered", exc, len(self._buffer))
                return False
            self._buffer.popleft()
        return True
