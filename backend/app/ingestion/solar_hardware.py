"""solar_hardware: the real ESP32 + INA219 mini-panel node (firmware/solar_hardware). ONE data source for the live twin and
for all three testbed topologies (testbed/hardware_node.py reads the same readings).

The ESP32 prints one JSON line per second over USB serial, e.g.
    {"node":"solar_hardware","t_ms":12345,"v_bus_v":3.412,"i_ma":18.7,"p_mw":63.8}
(the user's own flashed sketch prints {"node":"solar_01","ts":..,"voltage_v":..,"current_ma":..,"power_mw":..,"valid":true}; also accepted)
`parse_line` turns it into a NormalizedReading (source_type "live", provenance "sensed" - physically measured, no estimate).
Power is kW like every other source; the normal pipeline then normalises it per-unit of SOLAR_HARDWARE_RATED_KW.

Enabled by SOLAR_HARDWARE_PORT (e.g. COM3); unset = this task does nothing. Only one process can hold the serial port, so stop
the backend before running scripts/capture_solar_hardware.py (or point both at different ports).
"""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone

from app.config import settings
from app.ingestion.pipeline import ingest_reading
from app.models.reading import NormalizedReading

logger = logging.getLogger("sei")

SOLAR_HARDWARE_NODE_ID = "solar_hardware"


def parse_line(line: str) -> dict | None:
    """The sample dict (v_bus_v, i_ma, p_mw) from one serial line, or None for noise, boot text, error lines and bad values."""
    try:
        d = json.loads(line)
    except ValueError:
        return None
    # Two firmware dialects: ours (node "solar_hardware", v_bus_v/i_ma/p_mw) and the user's flashed sketch (node "solar_01",
    # voltage_v/current_ma/power_mw, plus valid). The serial port identifies the node, so its self-reported name is not used.
    if not isinstance(d, dict) or d.get("node") not in (SOLAR_HARDWARE_NODE_ID, "solar_01") or d.get("valid", True) is not True:
        return None
    try:
        s = {k: float(d[a] if a in d else d[b]) for k, a, b in
             (("v_bus_v", "v_bus_v", "voltage_v"), ("i_ma", "i_ma", "current_ma"), ("p_mw", "p_mw", "power_mw"))}
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in s.values()):
        return None
    return s


def build_reading(sample: dict) -> NormalizedReading:
    return NormalizedReading(
        node_id=SOLAR_HARDWARE_NODE_ID, source_type="live", type="solar", timestamp=datetime.now(timezone.utc),
        power_output=max(0.0, sample["p_mw"]) / 1e6,  # mW -> kW; INA219 can read slightly negative at zero light
        provenance="sensed", voltage_v=sample["v_bus_v"], current_ma=sample["i_ma"],
    )


async def run_solar_hardware() -> None:
    port = settings.solar_hardware_port
    if not port:
        logger.info("solar_hardware off (SOLAR_HARDWARE_PORT unset)")
        return
    import serial  # pyserial, imported here so the backend runs without it when the node is not used

    while True:  # reconnect forever: a USB unplug must not kill ingestion
        try:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = port, settings.solar_hardware_baud, 2
            ser.dtr = ser.rts = False  # opening must not reset the ESP32 (arduino.c needs ~30 s to boot before its first sample)
            await asyncio.to_thread(ser.open)
            logger.info("solar_hardware: reading %s @ %s baud", port, settings.solar_hardware_baud)
            while True:
                raw = await asyncio.to_thread(ser.readline)
                sample = parse_line(raw.decode("utf-8", "replace").strip()) if raw else None
                if sample is not None:
                    await ingest_reading(build_reading(sample))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("solar_hardware serial error on %s: %s (retrying in 5 s)", port, exc)
            await asyncio.sleep(5)


async def run_solar_hardware_mqtt() -> None:
    """Subscribe to the ESP32's MQTT topic (arduino.c publishes the same JSON on sei/solar/<NODE_ID>) and ingest each sample."""
    if not settings.mqtt_host:
        logger.info("solar_hardware MQTT off (MQTT_HOST unset)")
        return
    import paho.mqtt.client as mqtt

    loop = asyncio.get_running_loop()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sei-backend-solar")

    def on_connect(c, userdata, flags, reason_code, properties):
        logger.info("solar_hardware MQTT connected (%s), subscribing %s", reason_code, settings.mqtt_solar_topic)
        c.subscribe(settings.mqtt_solar_topic)  # re-subscribes after every reconnect

    def on_message(c, userdata, msg):  # paho network thread -> event loop
        sample = parse_line(msg.payload.decode("utf-8", "replace"))
        if sample is not None:
            asyncio.run_coroutine_threadsafe(ingest_reading(build_reading(sample)), loop)

    client.on_connect, client.on_message = on_connect, on_message
    client.reconnect_delay_set(1, 30)
    client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    client.loop_start()
    try:
        await asyncio.Event().wait()
    finally:
        client.loop_stop()
        client.disconnect()
