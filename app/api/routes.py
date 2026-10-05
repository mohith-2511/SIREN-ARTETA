import secrets, logging
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from app.core.config import settings
from app.database import crud, models as m
from app.services.tracking import engine
from app.services import routing, geo
from app.api.telemetry import TelemetryIn, ID_PATTERN, mqtt_bridge
from app.api.websocket import manager

log = logging.getLogger("bevims.api")
router = APIRouter(prefix="/api")


def require_key(key: Optional[str]):
    if not settings.TELEMETRY_API_KEY or not key or not secrets.compare_digest(key, settings.TELEMETRY_API_KEY):
        raise HTTPException(401, "Missing or invalid X-API-Key")


class VehicleIn(BaseModel):
    id: str = Field(pattern=ID_PATTERN)
    name: Optional[str] = Field(None, max_length=64)


class IncidentIn(BaseModel):
    kind: str = Field(pattern="^(congestion|accident|closure)$")
    lat: float = Field(ge=-90, le=90); lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(500, gt=0, le=5000); severity: float = Field(0.7, ge=0, le=1)
    description: str = Field("", max_length=200)


class ScenarioIn(BaseModel):
    name: str = Field(pattern="^(normal|congestion|accident|deviation|failure|critical_delay)$")
    vehicle_id: Optional[str] = Field(None, pattern=ID_PATTERN)


@router.post("/telemetry")
async def post_telemetry(t: TelemetryIn, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    try:
        s = engine.ingest(t)
    except KeyError:
        raise HTTPException(404, f"Vehicle {t.vehicle_id} is not registered (POST /api/vehicles first)")
    return {"ok": True, "status": s.status}


@router.get("/vehicles")
def vehicles():
    return engine.snapshot()["vehicles"]


@router.post("/vehicles", status_code=201)
def add_vehicle(v: VehicleIn, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    engine.register(v.id, v.name)
    return {"id": v.id}


@router.get("/vehicles/{vid}")
def vehicle(vid: str):
    if vid not in engine.vehicles:
        raise HTTPException(404, "Unknown vehicle")
    return next(v for v in engine.snapshot()["vehicles"] if v["id"] == vid)


@router.get("/vehicles/{vid}/telemetry")
def vehicle_telemetry(vid: str, limit: int = Query(100, ge=1, le=1000)):
    if vid not in engine.vehicles:
        raise HTTPException(404, "Unknown vehicle")
    return crud.rows(m.Telemetry, limit=limit, desc_by="id", vehicle_id=vid)


@router.get("/routes/{vid}")
def route(vid: str):
    s = engine.vehicles.get(vid)
    if not s:
        raise HTTPException(404, "Unknown vehicle")
    return dict(route_id=s.route_id, destination=s.destination, source=s.route_src,
                points=geo.simplify(s.route.pts, 250) if s.route else [], alternatives=s.alts)


@router.get("/alerts")
def alerts(limit: int = Query(50, ge=1, le=500)):
    return crud.rows(m.Alert, limit=limit, desc_by="id")


@router.get("/incidents")
def incidents():
    return engine.incidents


@router.post("/incidents", status_code=201)
def add_incident(i: IncidentIn, x_api_key: Optional[str] = Header(None)):
    require_key(x_api_key)
    r = crud.add(m.Incident(**i.model_dump(), source="OPERATOR"))
    engine.refresh_incidents()
    engine.alert("warn", None, f"Incident reported: {i.kind} ({i.description or 'no description'})")
    return r


@router.get("/hospitals")
def hospitals():
    return engine.hospitals


@router.get("/recommendations")
def recommendations():
    return crud.rows(m.DispatchRecommendation, limit=50, desc_by="id")


@router.post("/scenario")
async def scenario(s: ScenarioIn):
    from app.simulator.ambulance_simulator import simulator
    if not engine.simulation or simulator is None:
        raise HTTPException(409, "Scenarios require SIMULATION_MODE=true")
    try:
        return {"ok": True, "message": simulator.apply(s.name, s.vehicle_id)}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.get("/system/status")
def status():
    snap = engine.snapshot(len(manager.clients))
    return dict(status="ok", **snap["system"], routing_provider=settings.ROUTING_PROVIDER,
                mapbox_configured=bool(settings.MAPBOX_TOKEN), llm_configured=bool(settings.OPENROUTER_API_KEY),
                mqtt=dict(enabled=settings.MQTT_ENABLED, connected=mqtt_bridge.connected),
                telemetry_key_is_default=settings.TELEMETRY_API_KEY == "bevims-demo-key")
