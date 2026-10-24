import asyncio

from app.ingestion import solar_hardware
from app.twin.digital_twin import DigitalTwin, SOLAR_HARDWARE_RATED_KW, digital_twin
from app.twin.graph import twin

LINE = '{"node":"solar_hardware","t_ms":12345,"v_bus_v":3.412,"i_ma":18.7,"p_mw":63.8}'


def test_parse_line_accepts_samples_and_rejects_noise():
    s = solar_hardware.parse_line(LINE)
    assert s == {"v_bus_v": 3.412, "i_ma": 18.7, "p_mw": 63.8}
    for bad in ("", "ets Jun  8 2016 boot", "{not json", '{"node":"solar_hardware","err":"ina219_not_found"}',
                '{"node":"other","v_bus_v":1,"i_ma":1,"p_mw":1}', '{"node":"solar_hardware","v_bus_v":NaN,"i_ma":1,"p_mw":1}',
                '{"i2c_scan":["0x40"]}'):
        assert solar_hardware.parse_line(bad) is None


def test_parse_user_firmware_dialect():
    ok = '{"node":"solar_01","type":"solar","ts":398,"voltage_v":0.86,"current_ma":-0.1,"power_mw":-0.1,"valid":true}'
    assert solar_hardware.parse_line(ok) == {"v_bus_v": 0.86, "i_ma": -0.1, "p_mw": -0.1}
    assert solar_hardware.parse_line(ok.replace("true", "false")) is None


def test_reading_is_sensed_live_kw():
    r = solar_hardware.build_reading(solar_hardware.parse_line(LINE))
    assert (r.node_id, r.type, r.source_type, r.provenance) == ("solar_hardware", "solar", "live", "sensed")
    assert abs(r.power_output - 63.8e-6) < 1e-12
    assert solar_hardware.build_reading({"v_bus_v": 0.0, "i_ma": -0.1, "p_mw": -0.4}).power_output == 0.0


def test_node_only_in_live_twin():
    assert "solar_hardware" in {n["node_id"] for n in digital_twin.get_all_nodes()}
    assert "solar_hardware" in {n["node_id"] for n in twin.get_all_nodes()}
    assert len(DigitalTwin().get_all_nodes()) == 9


def test_ingest_normalises_per_unit(monkeypatch):
    from app.ingestion import pipeline
    async def noop(*a, **k): pass
    monkeypatch.setattr(pipeline.db, "insert_reading", noop)
    monkeypatch.setattr(pipeline.manager, "broadcast", noop)
    asyncio.run(pipeline.ingest_reading(solar_hardware.build_reading(solar_hardware.parse_line(LINE))))
    n = digital_twin.get_node("solar_hardware")
    assert n["health_status"] == "normal"
    norm = n["latest_reading"]["normalized"]
    assert norm["power_output"] == round(63.8e-6 / SOLAR_HARDWARE_RATED_KW, 4)
    assert norm["voltage"] == round(3.412 / 8.0, 4) and norm["current"] == round(18.7 / 400.0, 4)
