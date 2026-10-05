"""SIMULATION MODE: moves ambulances along real OSRM routes (or a labelled fallback estimate) and feeds the same
ingest path real EVT hardware uses. All telemetry/incidents produced here are tagged SIMULATION."""
import asyncio, math, random, time, logging
from datetime import datetime
from app.core.config import settings
from app.database import crud, models as m
from app.api.telemetry import TelemetryIn
from app.services import geo, routing
from app.services.tracking import engine

log = logging.getLogger("bevims.sim")
# (id, base location, base name, hospital or None = available/standby)
FLEET = [("AMB-101", (12.8452, 77.6602), "Electronic City", "St. John's Hospital"),
         ("AMB-102", (12.9698, 77.7500), "Whitefield", "Manipal Hospital"),
         ("AMB-103", (13.0358, 77.5970), "Hebbal", "Victoria Hospital"),
         ("AMB-104", (12.9177, 77.6233), "Silk Board", None),
         ("AMB-105", (12.9784, 77.6408), "Indiranagar", None)]
# deterministic demo timeline: (seconds into cycle, scenario, vehicle)
TIMELINE = [(40, "congestion", "AMB-101"), (130, "normal", None), (160, "deviation", "AMB-102"), (230, "normal", None),
            (260, "critical_delay", "AMB-103"), (420, "normal", None)]
CYCLE = 450


class SimVehicle:
    def __init__(s, vid, base, base_name, hosp):
        s.id, s.base, s.base_name, s.hosp = vid, base, base_name, hosp
        s.route = None; s.progress = 0.0; s.kmh = 40.0; s.factor = 1.0; s.offset = 0.0; s.target_off = 0.0
        s.silent = False; s.revert_at = None; s.inc_ids = []; s.busy = False; s.wait_until = 0.0
        s.pos = base; s.outbound = True; s.dest_name = None


class Simulator:
    def __init__(self):
        self.v, self.rng, self.t0, self.last_el, self.manual = {}, random.Random(42), time.time(), 0.0, False

    async def setup(self):
        for vid, base, bname, hosp in FLEET[:max(1, min(settings.SIMULATION_VEHICLES, len(FLEET)))]:
            engine.register(vid)
            self.v[vid] = sv = SimVehicle(vid, base, bname, hosp)
            if hosp:
                await self.start_trip(sv)

    async def start_trip(self, sv):
        sv.busy = True
        try:
            h = engine.find_hospital(sv.hosp)
            dest, name = ((h["lat"], h["lon"]), sv.hosp) if sv.outbound else (sv.base, f"Base: {sv.base_name}")
            rs = await routing.fetch_routes(sv.pos, dest, alts=False)
            sv.route = geo.Route(rs[0]["points"], rs[0]["duration_s"])
            sv.progress, sv.kmh, sv.dest_name = 0.0, sv.route.length / sv.route.duration * 3.6, name
            engine.set_route(sv.id, sv.route, name, dest, rs[0]["source"])
        except Exception as e:
            log.error("trip setup failed for %s: %s", sv.id, e); sv.wait_until = time.time() + 10
        finally:
            sv.busy = False

    async def run(self):
        engine.simulation = True
        await self.setup()
        engine.alert("info", None, "DEMO MODE: 5 simulated emergency vehicles active (SIMULATION data, not live Bengaluru traffic)")
        while True:
            await asyncio.sleep(1)
            try:
                self.tick()
            except Exception:
                log.exception("simulator tick error (continuing)")

    # ---------- scenarios ----------
    def apply(self, name, vid=None):
        vid = vid or next((k for k in ("AMB-102", "AMB-101", "AMB-103") if k in self.v and self.v[k].route), None)
        if vid not in self.v:
            raise KeyError(f"Unknown simulated vehicle {vid}")
        sv, now = self.v[vid], time.time()
        if name == "normal":
            for x in self.v.values():
                self._revert(x)
            crud.set_incident_active(source="SIMULATION"); engine.refresh_incidents()
            msg = "Normal operation restored"
        else:
            self._revert(sv); sv.revert_at = now + {"congestion": 150, "accident": 120, "deviation": 60, "critical_delay": 240}.get(name, 1e9)
            if name == "failure":
                sv.silent = True
            elif name == "deviation":
                sv.target_off = 350.0
            else:
                lat, lon, _ = (sv.route.point_at(sv.progress + 600) if sv.route else (*sv.pos, 0))
                kind, sev, rad, f = {"congestion": ("congestion", 0.8, 900, 0.35), "accident": ("accident", 0.9, 400, 0.15),
                                     "critical_delay": ("congestion", 0.95, 1200, 0.08)}[name]
                inc = crud.add(m.Incident(kind=kind, lat=lat, lon=lon, radius_m=rad, severity=sev, source="SIMULATION",
                                          description=f"SIMULATION: {name} scenario"))
                sv.inc_ids.append(inc["id"]); sv.factor = f; engine.refresh_incidents()
            msg = f"Scenario '{name}' applied to {vid}"
        if name != "normal":
            self.manual = True                      # operator took control: pause scripted autoplay
        engine.alert("info", vid if name != "normal" else None, "Scenario: " + msg)
        return msg

    def _revert(self, sv):
        sv.factor, sv.target_off, sv.silent, sv.revert_at = 1.0, 0.0, False, None
        for i in sv.inc_ids:
            crud.set_incident_active(iid=i)
        if sv.inc_ids:
            sv.inc_ids = []; engine.refresh_incidents()

    def _autoplay(self, now):
        if not settings.DEMO_AUTOPLAY or self.manual:
            return
        el = (now - self.t0) % CYCLE
        for t, name, vid in TIMELINE:
            if (self.last_el < t <= el) or (el < self.last_el and (t > self.last_el or t <= el)):
                try:
                    self.apply(name, vid); self.manual = False
                except KeyError:
                    pass
        self.last_el = el

    # ---------- movement ----------
    def tick(self):
        now = time.time()
        self._autoplay(now)
        for sv in self.v.values():
            if sv.revert_at and now > sv.revert_at:
                self._revert(sv); engine.alert("info", sv.id, "simulated disruption cleared")
            if sv.silent:
                continue
            speed, heading, dest = 0.0, 0.0, None
            if sv.route:
                dest = sv.dest_name
                if sv.progress >= sv.route.length - 1:
                    sv.progress = sv.route.length
                    if not sv.wait_until:
                        sv.wait_until = now + 8
                    elif now > sv.wait_until and not sv.busy:
                        sv.wait_until = 0; sv.outbound = not sv.outbound; sv.pos = sv.route.pts[-1]
                        asyncio.get_running_loop().create_task(self.start_trip(sv))
                else:
                    speed = max(0.0, sv.kmh * sv.factor * (1 + self.rng.uniform(-0.06, 0.06)))
                    sv.progress += speed / 3.6
                lat, lon, heading = sv.route.point_at(sv.progress)
                sv.offset += max(-15, min(15, sv.target_off - sv.offset))
                th = math.radians(heading)
                lat += -math.sin(th) * sv.offset / 110540
                lon += math.cos(th) * sv.offset / (111320 * math.cos(math.radians(lat)))
                sv.pos = (lat, lon)
            lat, lon = sv.pos
            try:
                engine.ingest(TelemetryIn(vehicle_id=sv.id, timestamp=datetime.now(), latitude=lat, longitude=lon,
                                          speed=round(speed, 1), heading=round(heading, 1), emergency=bool(sv.route), destination=dest,
                                          route_id=engine.vehicles[sv.id].route_id))
            except Exception as e:
                log.warning("sim telemetry rejected for %s: %s", sv.id, e)


simulator = Simulator()
