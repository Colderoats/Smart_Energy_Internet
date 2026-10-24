"""Time-limited capture from the solar_hardware ESP32 (never an open-ended monitor).

    cd backend && venv\\Scripts\\python scripts\\capture_solar_hardware.py --port COM3 [--seconds 30] [--out PATH]

Writes one JSON line per valid sample ({"ts","v_bus_v","i_ma","p_mw","pu_power"}) and prints a summary. `pu_power` is the same
per-unit value the pipeline stores as normalized.power_output. Stop the backend first: only one process can hold the port.
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.solar_hardware import parse_line  # noqa: E402
from app.models.reading import normalized_values  # noqa: E402
from app.twin.digital_twin import SOLAR_HARDWARE_RATED_KW  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "solar_hardware" / "capture.jsonl"))
    a = ap.parse_args()
    import serial

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows, other = [], 0
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = a.port, a.baud, 1
    ser.dtr = ser.rts = False  # opening the port must not reset the ESP32 (its boot can take 30 s before the first sample)
    ser.open()
    with ser, out.open("w") as f:
        ser.reset_input_buffer()
        end = time.monotonic() + a.seconds
        while time.monotonic() < end:
            raw = ser.readline().decode("utf-8", "replace").strip()
            s = parse_line(raw) if raw else None
            if s is None:
                other += bool(raw)
                continue
            s["pu_power"] = normalized_values({"power_output": max(0.0, s["p_mw"]) / 1e6}, SOLAR_HARDWARE_RATED_KW)["power_output"]
            s["ts"] = datetime.now(timezone.utc).isoformat()
            rows.append(s)
            f.write(json.dumps(s) + "\n")
    print(f"{len(rows)} samples in {a.seconds:.0f} s -> {out} ({other} non-sample lines ignored)")
    for k in ("v_bus_v", "i_ma", "p_mw", "pu_power"):
        if rows:
            v = [r[k] for r in rows]
            print(f"  {k:9s} min {min(v):9.3f}  mean {statistics.fmean(v):9.3f}  max {max(v):9.3f}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
