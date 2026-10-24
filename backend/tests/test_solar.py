import asyncio

from app.ingestion import solar_source
from app.twin.digital_twin import DigitalTwin, digital_twin
from app.twin.graph import twin


def test_dataset_and_reading():
    rows = solar_source.load_dataset()
    assert len(rows) == 24 and rows[0]["ac_power_kw"] == 0 and max(r["ac_power_kw"] for r in rows) <= 50
    r = solar_source.build_reading(rows[12])
    assert r.type == "solar" and r.provenance == "replayed_dataset" and r.power_output > 0


def test_solar_node_only_in_live_twin():
    assert "solar_01" in {n["node_id"] for n in digital_twin.get_all_nodes()}
    assert "solar_01" in {n["node_id"] for n in twin.get_all_nodes()}
    assert len(DigitalTwin().get_all_nodes()) == 9  # AI default topology unchanged


def test_ingest_solar(monkeypatch):
    from app.ingestion import pipeline
    async def noop(*a, **k): pass
    monkeypatch.setattr(pipeline.db, "insert_reading", noop)
    monkeypatch.setattr(pipeline.manager, "broadcast", noop)
    asyncio.run(pipeline.ingest_reading(solar_source.build_reading(solar_source.load_dataset()[12])))
    n = digital_twin.get_node("solar_01")
    assert n["health_status"] == "normal" and n["latest_reading"]["normalized"]["power_output"] > 0
