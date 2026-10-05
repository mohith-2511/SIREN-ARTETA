# BEVIMS — Bengaluru Emergency Vehicle Intelligence & Monitoring System

Real-time emergency-vehicle tracking and decision support. FastAPI + WebSocket backend, SQLite via SQLAlchemy, Leaflet/OpenStreetMap dashboard.

## Install & run (Windows)
1. `install.bat` (or `install.ps1`) — creates `.venv`, installs requirements, creates `.env`, initialises + seeds the DB
2. `run.bat` — starts the server and opens http://127.0.0.1:8000 (Ctrl+C = clean shutdown)
3. Tests: `.venv\Scripts\activate` then `pytest`

## Demo mode (default, `SIMULATION_MODE=true`)
5 simulated ambulances (AMB-101..105) run between real Bengaluru locations. AMB-101/102/103 are on missions; AMB-104/105 are available standby vehicles (backup candidates). Routes come from the public OSRM server (real roads). `DEMO_AUTOPLAY=true` replays a fixed timeline (congestion → deviation → critical delay, 450 s cycle); the **DEMO SCENARIO** buttons trigger events on demand for the selected vehicle (pressing one pauses autoplay).

## Real hardware (EVT transponder)
* **HTTP**: `POST /api/telemetry` with header `X-API-Key: <TELEMETRY_API_KEY>`
  ```json
  {"vehicle_id":"AMB-101","timestamp":"2026-10-05T11:30:00","latitude":12.9716,"longitude":77.5946,"speed":52,"heading":145,"emergency":true,"destination":"Victoria Hospital","route_id":"R001"}
  ```
  Register the vehicle first: `POST /api/vehicles {"id":"AMB-101"}` (same header). Unregistered IDs are rejected. If `destination` matches a seeded hospital, the planned route is computed automatically.
* **MQTT**: set `MQTT_ENABLED=true`, `MQTT_BROKER`, etc. in `.env`; publish to `ambulance/{vehicle_id}/telemetry` (the topic's ID is authoritative).
* **Change `TELEMETRY_API_KEY` before connecting hardware.**

## How it works
| Module | What it does |
|---|---|
| `services/deviation.py` | Perpendicular distance to planned polyline, time off-route, heading difference, divergence. Fires only after `DEVIATION_DISTANCE_THRESHOLD` (100 m) held for `DEVIATION_TIME_THRESHOLD` (15 s) |
| `services/cause_detection.py` | Rule-based classifier (`classify(features)->dict`, swappable for ML). Confidence is a heuristic score, not a probability; below 0.35 → "Unknown / Low" |
| `services/eta.py` | Blends current speed, recent history and time-of-day/congestion-adjusted free-flow speed |
| `services/traffic.py` + `config.yaml` | Time-of-day multipliers (**simulated, not measured**) + incident-based congestion |
| `services/dispatch.py` | Route scoring (time, congestion, incident risk, distance weights in `config.yaml`) and backup-vehicle selection |
| `services/explain.py` | Template explanations; optionally polished by an LLM if `OPENROUTER_API_KEY` is set |

Status colours: green available · blue en route normally · orange delayed (≥3 min) · red deviation or critical delay (≥10 min) · grey offline. The EMERGENCY tag marks vehicles transmitting `emergency:true`.

## Honest limitations
* **No live traffic.** Congestion = simulated time-of-day model + incidents (simulated or operator-entered via `POST /api/incidents`). The UI labels it SIMULATED. `MAPBOX_TOKEN` is reserved; only OSRM routing is implemented.
* If OSRM is unreachable the app uses clearly-labelled **fallback** curved routes (not road-accurate) and the footer shows DEGRADED.
* "Current road" is the nearest known landmark, not reverse-geocoded street data.
* Backup response time uses straight-line distance × 1.3 (an estimate). It is a recommendation for the control-room operator only.
* Scenario endpoint (`POST /api/scenario`) is unauthenticated — intended for local demos only.
* LLM polishing and the live MQTT path were not exercised in my test environment (no broker/API key); HTTP, WebSocket and the simulator were.
* The dashboard loads Leaflet and OSM tiles from the internet; CSS/JS are inline in `templates/dashboard.html`.
