import asyncio, time, logging, statistics
from collections import deque
from datetime import datetime, timedelta
from app.core.config import settings, cfg
from app.database import crud, models as m
from . import geo, traffic, routing, dispatch, explain
from .eta import predictor
from .deviation import DeviationDetector
from .cause_detection import classifier

log = logging.getLogger("bevims.tracking")
hm = lambda d: d.strftime("%H:%M") if d else None
DEV0 = dict(distance_m=0, off_seconds=0, heading_diff=0, deviated=False, divergence_m=0, along_m=0, nearest=None)


class VehicleState:
    def __init__(s, vid, name=None):
        s.id, s.name = vid, name or vid
        s.lat = s.lon = None; s.speed = 0.0; s.heading = 0.0
        s.emergency = False; s.destination = None; s.route_id = None; s.available = True
        s.route = None; s.dest_pt = None; s.planned_eta = None; s.planned_dur = 0; s.route_src = None
        s.last_rx = 0.0; s.online = False; s.status = "offline"
        s.travelled = 0.0; s.along0 = None; s.off_since = None; s.dev = dict(DEV0)
        s.current_eta = None; s.delay_min = 0.0; s.cause = None
        s.alts = []; s.best = None; s.backup = None; s.replan_t = 0.0
        s.hist = deque(maxlen=90); s.trail = deque(maxlen=240); s.speeds = deque(maxlen=60)
        s.flags = set(); s.anom = 0; s.gps_anomaly = False; s.road = ""; s.explanation = ""; s.polished = None
        s.route_pending = False

    def public(s, now):
        return dict(
            id=s.id, name=s.name, lat=s.lat, lon=s.lon, speed=round(s.speed), heading=round(s.heading), emergency=s.emergency,
            destination=s.destination, route_id=s.route_id, road=s.road, status=s.status, online=s.online, available=s.available,
            age_s=round(now - s.last_rx, 1) if s.last_rx else None,
            planned_eta=hm(s.planned_eta), current_eta=hm(s.current_eta), delay_min=round(s.delay_min, 1),
            planned_km=round(s.route.length / 1000, 2) if s.route else None, travelled_km=round(s.travelled / 1000, 2),
            route_source=s.route_src, dev=s.dev, cause=s.cause, backup=s.backup, best=s.best,
            alts=[{k: v for k, v in a.items()} for a in s.alts], explanation=s.explanation,
            hist=list(s.hist)[-60:], trail=[list(p) for p in list(s.trail)[-150:]])


class TrackingEngine:
    def __init__(self):
        self.vehicles, self.incidents, self.hospitals = {}, [], []
        self.alerts = deque(maxlen=100)
        self.detector = DeviationDetector()
        self.simulation = False

    # ---------- setup ----------
    def load(self):
        for v in crud.rows(m.Vehicle, limit=1000):
            self.register(v["id"], v["name"], persist=False)
        self.hospitals = crud.rows(m.Hospital, limit=200)
        self.refresh_incidents()

    def register(self, vid, name=None, persist=True):
        if vid not in self.vehicles:
            self.vehicles[vid] = VehicleState(vid, name)
            if persist:
                crud.upsert_vehicle(vid, name)
        return self.vehicles[vid]

    def refresh_incidents(self):
        self.incidents = crud.rows(m.Incident, limit=500, active=True)

    def find_hospital(self, name):
        n = (name or "").lower()
        return next((h for h in self.hospitals if n and (n in h["name"].lower() or h["name"].lower() in n)), None)

    def alert(self, level, vid, msg):
        a = crud.add(m.Alert(level=level, vehicle_id=vid, message=msg))
        a["ts"] = a["ts"].strftime("%H:%M:%S")
        self.alerts.appendleft(a)
        log.info("%s %s", vid or "SYSTEM", msg)

    def set_route(self, vid, route, dest_name, dest_pt, source="osrm", route_id=None):
        s = self.vehicles[vid]
        s.route, s.dest_pt, s.destination, s.route_src = route, dest_pt, dest_name, source
        s.route_id = route_id or f"R-{vid}-{int(time.time())}"
        s.planned_dur = route.duration * traffic.period()[1]
        s.planned_eta = datetime.now() + timedelta(seconds=s.planned_dur)
        s.travelled, s.along0, s.off_since, s.dev = 0.0, None, None, dict(DEV0)
        s.available, s.alts, s.best, s.flags, s.cause = False, [], None, set(), None
        crud.save_route(s.route_id, vid, dest_name, route.length, route.duration, source, s.planned_eta, route.pts)

    async def _auto_route(self, s, hosp):
        try:
            rs = await routing.fetch_routes((s.lat, s.lon), (hosp["lat"], hosp["lon"]), alts=False)
            self.set_route(s.id, geo.Route(rs[0]["points"], rs[0]["duration_s"]), hosp["name"], (hosp["lat"], hosp["lon"]), rs[0]["source"])
            self.alert("info", s.id, f"Planned route to {hosp['name']} computed ({rs[0]['source']})")
        finally:
            s.route_pending = False

    # ---------- ingest ----------
    def ingest(self, t):
        s = self.vehicles.get(t.vehicle_id)
        if s is None:
            raise KeyError(t.vehicle_id)
        now = time.time()
        if not s.online:
            s.online = True
            if s.last_rx:
                self.alert("ok", s.id, "back online - telemetry resumed")
        log.debug("%s telemetry received", s.id)
        s.gps_anomaly = False
        if s.lat is not None and s.last_rx:
            d = geo.haversine(s.lat, s.lon, t.latitude, t.longitude)
            if d / max(now - s.last_rx, 0.2) * 3.6 > 180 and s.anom < 3:     # implausible jump: hold last good fix
                s.anom += 1; s.gps_anomaly = True; s.last_rx = now
                self.alert("warn", s.id, f"GPS anomaly: implausible {d:.0f} m jump ignored")
                return s
            s.travelled += d
        s.anom = 0
        s.lat, s.lon, s.speed, s.heading, s.emergency = t.latitude, t.longitude, t.speed, t.heading, t.emergency
        s.last_rx = now
        s.available = not t.destination
        if t.destination and t.destination != s.destination:
            s.destination = t.destination
        s.road = geo.nearest_landmark(s.lat, s.lon)
        s.trail.append((round(s.lat, 6), round(s.lon, 6)))
        crud.add(m.Telemetry(vehicle_id=s.id, ts=t.timestamp or datetime.now(), latitude=s.lat, longitude=s.lon, speed=s.speed,
                             heading=s.heading, emergency=s.emergency, destination=t.destination, route_id=t.route_id))
        if s.route is None and t.destination and not s.route_pending:
            h = self.find_hospital(t.destination)
            if h:
                try:
                    s.route_pending = True
                    asyncio.get_running_loop().create_task(self._auto_route(s, h))
                except RuntimeError:
                    s.route_pending = False
        self._analyse(s, now)
        return s

    # ---------- analysis ----------
    def _analyse(self, s, now):
        s.speeds.append(s.speed)
        if s.available or not s.route:
            s.delay_min, s.current_eta, s.cause, s.dev = 0.0, None, None, dict(DEV0)
            s.hist.append([s.speed, round(s.travelled / 1000, 2), None])
            self._set_status(s); return
        d = self.detector.evaluate(s, now)
        remaining = max(s.route.length - d["along_m"], 0) + (d["distance_m"] if d["deviated"] else 0)
        cong = traffic.congestion_at(s.lat, s.lon, self.incidents)
        ahead = traffic.ahead_congestion(s.route, d["along_m"], self.incidents)
        eta_s = predictor.predict(remaining, s.speed, list(s.speeds), max(cong, ahead), route_kmh=s.route.length / s.route.duration * 3.6)
        s.current_eta = datetime.now() + timedelta(seconds=eta_s)
        s.delay_min = (s.current_eta - s.planned_eta).total_seconds() / 60
        s.hist.append([s.speed, round(s.travelled / 1000, 2), round(eta_s / 60, 1)])
        prior, recent = list(s.speeds)[:-8], list(s.speeds)[-5:]
        drop = max(0.0, 1 - statistics.mean(recent) / statistics.mean(prior)) if len(prior) >= 8 and statistics.mean(prior) > 10 else 0.0
        issue = d["deviated"] or s.delay_min >= 2 or drop > 0.25 or s.gps_anomaly
        if issue:
            f = dict(speed=s.speed, speed_drop=drop, congestion=cong, ahead_congestion=ahead,
                     incidents=traffic.nearby_incidents(s.lat, s.lon, self.incidents), deviated=d["deviated"],
                     deviation_m=d["distance_m"], heading_diff=d["heading_diff"], gps_anomaly=s.gps_anomaly)
            prev = s.cause["cause"] if s.cause else None
            s.cause = classifier.classify(f)
            if s.cause["cause"] != prev and s.cause["cause"] != "unknown":
                self.alert("info", s.id, f"Cause classified as {s.cause['label'].lower()} (heuristic confidence {s.cause['confidence'] * 100:.0f}%)")
        else:
            s.cause = None
        warn, crit = cfg("dispatch.warn_delay_min"), cfg("dispatch.critical_delay_min")
        if d["deviated"] and "dev" not in s.flags:
            s.flags.add("dev")
            self.alert("warn", s.id, f"deviated from planned route by {d['distance_m']:.0f} m (planned {s.route.length / 1000:.1f} km, travelled {s.travelled / 1000:.1f} km)")
        elif "dev" in s.flags and d["distance_m"] < self.detector.dist_m:
            s.flags.discard("dev"); self.alert("ok", s.id, "returned to planned route")
        if s.delay_min >= warn and "delay" not in s.flags:
            s.flags.add("delay"); self.alert("warn", s.id, f"predicted delay +{s.delay_min:.0f} minutes")
        elif s.delay_min < warn / 2:
            s.flags.discard("delay")
        if (d["deviated"] or s.delay_min >= warn or ahead > 0.6) and time.time() - s.replan_t > 20:
            s.replan_t = time.time()
            try:
                asyncio.get_running_loop().create_task(self._replan(s))
            except RuntimeError:
                pass
        elif not (d["deviated"] or s.delay_min >= warn / 2 or ahead > 0.4) and (s.best or s.alts):
            s.alts, s.best, s.polished = [], None, None
        self._check_backup(s, False, crit)
        s.explanation = explain.explain(s) if (s.dev["deviated"] or s.delay_min >= 1 or s.best or s.backup) else ""
        if s.polished and time.time() - s.polished[0] < 60:
            s.explanation = s.polished[1]
        self._set_status(s)

    async def _replan(self, s):
        try:
            rs = await routing.fetch_routes((s.lat, s.lon), s.dest_pt)
            s.alts = dispatch.score_routes(rs, self.incidents)
            s.best = s.alts[0]
            log.info("%s alternative routes calculated", s.id)
            self.alert("ok", s.id, f"Alternative Route {s.best['label']} calculated ({s.best['eta_min']:.0f} min, {s.best['distance_km']} km, {s.best['traffic']} traffic)")
            s.explanation = explain.explain(s)
            txt = await explain.polish(s.explanation)
            if txt:
                s.polished = (time.time(), txt)
        except Exception as e:
            log.error("replan failed for %s: %s", s.id, e)

    def _check_backup(self, s, offline, crit=None):
        crit = crit or cfg("dispatch.critical_delay_min")
        need = offline or s.delay_min >= crit
        if need and not s.backup and s.lat is not None:
            rec = dispatch.select_backup(s, list(self.vehicles.values()), self.incidents, delay_min=s.delay_min)
            if rec:
                if offline:
                    rec["reason"] = "Primary vehicle stopped transmitting while on mission. " + rec["reason"]
                s.backup = rec
                crud.add(m.DispatchRecommendation(primary_id=s.id, backup_id=rec["backup_id"], distance_km=rec["distance_km"],
                         response_min=rec["response_min"], delay_min=rec["delay_min"], reason=rec["reason"]))
                log.info("Backup vehicle recommendation generated")
                self.alert("crit", s.id, f"BACKUP RECOMMENDED: {rec['backup_id']} ({rec['distance_km']} km, ~{rec['response_min']} min) - operator decision required")
            elif "nobackup" not in s.flags:
                s.flags.add("nobackup"); self.alert("crit", s.id, "critical delay but no available backup vehicle online")
        elif s.backup and not offline and s.online and s.delay_min < crit - 3:
            s.backup = None; s.flags.discard("nobackup"); crud.deactivate_recs(s.id)

    def _set_status(self, s):
        crit, warn = cfg("dispatch.critical_delay_min"), cfg("dispatch.warn_delay_min")
        s.status = ("offline" if not s.online else "available" if s.available else
                    "deviation" if (s.dev["deviated"] or s.delay_min >= crit) else
                    "delayed" if s.delay_min >= warn else "en_route")

    # ---------- periodic ----------
    def monitor(self):
        now = time.time()
        for s in self.vehicles.values():
            if s.online and s.last_rx and now - s.last_rx > settings.OFFLINE_AFTER_SECONDS:
                s.online = False
                self.alert("crit" if not s.available else "warn", s.id, f"OFFLINE - no telemetry for {now - s.last_rx:.0f}s (last seen: {s.road})")
                if not s.available and s.route:
                    self._check_backup(s, True)
                    s.explanation = explain.explain(s)
            self._set_status(s)

    def snapshot(self, ws_clients=0):
        now = time.time()
        vs = [v.public(now) for v in self.vehicles.values()]
        per, mult = traffic.period()
        return dict(
            server_time=datetime.now().strftime("%H:%M:%S"), vehicles=vs,
            incidents=[i for i in self.incidents], alerts=list(self.alerts)[:40],
            system=dict(mode="DEMO MODE" if self.simulation else "LIVE TELEMETRY", simulation=self.simulation,
                        online=sum(v["online"] for v in vs), total=len(vs),
                        deviations=sum(v["dev"]["deviated"] for v in vs), delays=sum(v["delay_min"] >= cfg("dispatch.warn_delay_min") for v in vs),
                        backups=sum(1 for v in vs if v["backup"]), routing=routing.state["last_source"] or "idle",
                        routing_msg=routing.state["message"], traffic_period=per, traffic_multiplier=mult, ws_clients=ws_clients,
                        dev_threshold=self.detector.dist_m))


engine = TrackingEngine()
