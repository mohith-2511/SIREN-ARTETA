from pathlib import Path
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")
    APP_ENV: str = "development"
    DEBUG: bool = True
    DATABASE_URL: str = "sqlite:///./data/bevims.db"
    MQTT_ENABLED: bool = False
    MQTT_BROKER: str = ""
    MQTT_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    ROUTING_PROVIDER: str = "osrm"
    OSRM_URL: str = "https://router.project-osrm.org"
    MAPBOX_TOKEN: str = ""
    OPENROUTER_API_KEY: str = ""
    LLM_MODEL: str = "openai/gpt-4o-mini"
    SIMULATION_MODE: bool = True
    SIMULATION_VEHICLES: int = 5
    DEMO_AUTOPLAY: bool = True
    WEBSOCKET_UPDATE_INTERVAL: float = 1.0
    TELEMETRY_API_KEY: str = "bevims-demo-key"
    CORS_ORIGINS: str = "http://127.0.0.1:8000,http://localhost:8000"
    DEVIATION_DISTANCE_THRESHOLD: float = 100
    DEVIATION_TIME_THRESHOLD: float = 15
    OFFLINE_AFTER_SECONDS: float = 10


settings = Settings()

DEFAULTS = {
    "traffic": {"morning_peak": {"start": 8, "end": 11, "multiplier": 1.5},
                "afternoon": {"start": 11, "end": 16, "multiplier": 1.0},
                "evening_peak": {"start": 16, "end": 21, "multiplier": 1.7},
                "night": {"multiplier": 0.8}},
    "scoring": {"time": 0.5, "congestion": 0.2, "incident_risk": 0.2, "distance": 0.1},
    "dispatch": {"critical_delay_min": 10, "warn_delay_min": 3, "free_flow_kmh": 35, "road_factor": 1.3},
}
try:
    _y = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
except Exception:
    _y = {}


def cfg(path: str, default=None):
    """cfg('dispatch.free_flow_kmh') - config.yaml first, then built-in defaults."""
    for src in (_y, DEFAULTS):
        cur = src
        for k in path.split("."):
            cur = cur.get(k) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur is not None:
            return cur
    return default
