r"""Set-2 TC02 - broker unreachable during publish: the message is buffered and retried after reconnection.
Run with the backend venv:  backend\venv\Scripts\python -m pytest tests\test_set2_tc02_broker.py -q -s"""
from app.ingestion.buffered_publisher import BufferedPublisher


class FakeBroker:
    def __init__(self):
        self.up = True
        self.received: list[tuple[str, bytes]] = []

    def send(self, topic, payload):
        if not self.up:
            raise ConnectionError("broker unreachable")
        self.received.append((topic, payload))


def test_buffered_while_down_and_retried_in_order_after_reconnect():
    b = FakeBroker()
    pub = BufferedPublisher(b.send)
    assert pub.publish("sei/solar_01", b"m0") is True
    b.up = False
    assert pub.publish("sei/solar_01", b"m1") is False  # publish during the outage: not lost, not raised
    assert pub.publish("sei/solar_01", b"m2") is False
    assert pub.buffered == 2 and [p for _, p in b.received] == [b"m0"]
    b.up = True
    assert pub.publish("sei/solar_01", b"m3") is True   # reconnection: buffered messages go first, in order
    assert [p for _, p in b.received] == [b"m0", b"m1", b"m2", b"m3"]
    assert pub.buffered == 0 and pub.dropped == 0
    print("\n[TC02-set2] 2 messages buffered during the outage, re-sent in order after reconnection:", [p for _, p in b.received])


def test_buffer_is_bounded_and_counts_drops():
    b = FakeBroker()
    b.up = False
    pub = BufferedPublisher(b.send, max_buffered=3)
    for i in range(5):
        pub.publish("t", str(i).encode())
    assert pub.buffered == 3 and pub.dropped == 2
    b.up = True
    assert pub.flush() is True
    assert [p for _, p in b.received] == [b"2", b"3", b"4"]
