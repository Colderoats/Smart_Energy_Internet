from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    postgres_user: str = "sei_user"
    postgres_password: str = "sei_password"
    postgres_db: str = "sei_db"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Demo locations for the live wind/hydro nodes (Open-Meteo needs
    # lat/lon, not a place name). Muppandal is one of India's largest
    # onshore wind farm clusters; Mettur Dam is a real hydro plant on the
    # Kaveri. Both are placeholders — override via env if you want
    # different sites.
    wind_node_lat: float = 8.15
    wind_node_lon: float = 77.55
    hydro_node_lat: float = 11.7896
    hydro_node_lon: float = 77.7885

    # How often the live poller fetches fresh values from Open-Meteo. The
    # underlying source data itself only refreshes ~hourly (wind) / daily
    # (hydro) — polling faster just re-reads the same cached value more
    # often. 60s keeps the demo visibly ticking without hammering the API.
    live_poll_interval_seconds: int = 60

    # Directory holding the SCADA CSV files for Stage 3 replay (the real
    # Kelmarsh wind-farm dataset — see app/ingestion/scada_replay.py).
    scada_data_dir: Path = REPO_ROOT / "backend" / "data" / "scada"
    scada_replay_interval_seconds: float = 2.0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
