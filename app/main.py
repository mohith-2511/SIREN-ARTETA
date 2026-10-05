import asyncio, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings, ROOT
from app.core.logging import setup_logging
from app.database import crud
from app.services.tracking import engine
from app.api.routes import router
from app.api.websocket import manager, ws_endpoint
from app.api.telemetry import mqtt_bridge

log = logging.getLogger("bevims")


@asynccontextmanager
async def lifespan(app):
    setup_logging(settings.DEBUG)
    crud.init_db(); crud.seed(vehicles=settings.SIMULATION_MODE)
    engine.load()
    tasks = [asyncio.create_task(manager.broadcast_loop())]
    if settings.SIMULATION_MODE:
        from app.simulator.ambulance_simulator import simulator
        tasks.append(asyncio.create_task(simulator.run()))
        log.info("SYSTEM STATUS: DEMO MODE - simulated vehicles starting")
    else:
        log.info("Real transponder mode: POST /api/telemetry (X-API-Key) or MQTT ambulance/{id}/telemetry")
    if settings.MQTT_ENABLED:
        mqtt_bridge.start(asyncio.get_running_loop(), engine.ingest, settings)
    else:
        log.info("MQTT disabled (set MQTT_ENABLED=true and MQTT_BROKER in .env to enable)")
    if not settings.MAPBOX_TOKEN and not settings.OPENROUTER_API_KEY:
        log.info("No optional API keys set: using OSRM routing and template explanations")
    yield
    mqtt_bridge.stop()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="BEVIMS", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
                   allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(router)
app.add_api_websocket_route("/ws", ws_endpoint)
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")


@app.exception_handler(Exception)
async def unhandled(request, exc):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "Internal error - see server log"}, status_code=500)


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(ROOT / "app" / "templates" / "dashboard.html")
