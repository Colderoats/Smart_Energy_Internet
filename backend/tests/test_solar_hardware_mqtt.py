"""MQTT path for solar_hardware. Needs the Mosquitto container on localhost:1883 (docker compose up -d mosquitto); skipped otherwise."""
import asyncio
import socket

import pytest

from app.config import settings
from app.ingestion import pipeline, solar_hardware
from app.twin.digital_twin import digital_twin


def _broker_up() -> bool:
    try:
        socket.create_connection(("localhost", 1883), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _broker_up(), reason="Mosquitto not running on localhost:1883")
def test_mqtt_sample_reaches_twin(monkeypatch):
    import paho.mqtt.publish as publish

    async def noop(*a, **k): pass
    monkeypatch.setattr(pipeline.db, "insert_reading", noop)
    monkeypatch.setattr(pipeline.manager, "broadcast", noop)
    monkeypatch.setattr(settings, "mqtt_host", "localhost")
    msg = '{"node":"solar_01","type":"solar","ts":1,"voltage_v":0.9,"current_ma":10.0,"power_mw":9.0,"valid":true}'

    async def go():
        task = asyncio.create_task(solar_hardware.run_solar_hardware_mqtt())
        for _ in range(30):  # publish until the subscription is live
            publish.single("sei/solar/solar_01", msg, hostname="localhost")
            await asyncio.sleep(0.2)
            r = digital_twin.get_node("solar_hardware")["latest_reading"]
            if r and abs(r["power_output"] - 9e-6) < 1e-12:
                break
        task.cancel()
        return digital_twin.get_node("solar_hardware")["latest_reading"]

    r = asyncio.run(go())
    assert r and r["node_id"] == "solar_hardware" and abs(r["power_output"] - 9e-6) < 1e-12
