import time, pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.api.telemetry import TelemetryIn
from app.services import geo, traffic, dispatch
from app.services.deviation import DeviationDetector
from app.services.eta import predictor
from app.services.cause_detection import classifier
from app.services.tracking import VehicleState

# straight ~2.2 km east-west road at Bengaluru latitude
ROUTE = geo.Route([(12.9716, 77.5946 + i * 0.002) for i in range(11)], 300)


def test_gps_validation():
    ok = TelemetryIn(vehicle_id="AMB-101", latitude=12.97, longitude=77.59, speed=40, heading=90)
    assert ok.speed == 40
    for bad in (dict(latitude=95, longitude=77), dict(latitude=12, longitude=200), dict(latitude=0, longitude=0),
                dict(latitude=float("nan"), longitude=77), dict(latitude=12, longitude=77, speed=-5), dict(latitude=12, longitude=77, vehicle_id="../x")):
        with pytest.raises(ValidationError):
            TelemetryIn(**{"vehicle_id": "AMB-101", **bad})


def test_distance_calculation():
    assert abs(geo.haversine(12.9716, 77.5946, 12.9716, 77.6946) - 10850) < 100      # 0.1 deg lon ~ 10.85 km
    d, along, hd, _ = ROUTE.nearest(12.9716 + 0.0009, 77.5946 + 0.01)             # ~100 m north of route
    assert 95 < d < 105 and abs(hd - 90) < 1 and 1000 < along < 1200


def _state(offset_deg):
    s = VehicleState("AMB-T"); s.route = ROUTE; s.speed = 40; s.heading = 90
    s.lat, s.lon = 12.9716 + offset_deg, 77.6046
    return s


def test_deviation_requires_distance_and_time():
    det, s = DeviationDetector(100, 15), _state(0.0045)             # ~500 m off
    assert not det.evaluate(s, 1000)["deviated"]                    # just left route: time threshold not met
    assert det.evaluate(s, 1016)["deviated"]                        # 16 s later: deviation
    assert det.evaluate(s, 1016)["distance_m"] > 400
    s2 = _state(0.0002)                                             # ~22 m: GPS jitter only
    assert not det.evaluate(s2, 0)["deviated"] and not det.evaluate(s2, 100)["deviated"]


def test_deviation_resets_when_back_on_route():
    det, s = DeviationDetector(100, 15), _state(0.0045)
    det.evaluate(s, 0); s.lat = 12.9716
    assert det.evaluate(s, 30)["deviated"] is False and s.off_since is None


def test_eta_slower_speed_means_later():
    fast = predictor.predict(5000, 50, [50] * 10, 0, 40)
    slow = predictor.predict(5000, 8, [50] * 5 + [8] * 5, 0.8, 40)
    assert slow > fast * 1.5 and fast > 0


def test_traffic_periods_and_congestion():
    assert traffic.period(datetime(2026, 10, 5, 9))[1] == 1.5 and traffic.period(datetime(2026, 10, 5, 17))[1] == 1.7
    assert traffic.period(datetime(2026, 10, 5, 2))[1] == 0.8
    inc = [dict(kind="congestion", lat=12.97, lon=77.59, radius_m=500, severity=0.9, active=True)]
    assert traffic.congestion_at(12.97, 77.59, inc) > 0.8 > traffic.congestion_at(13.1, 77.7, inc)


def _f(**k):
    base = dict(speed=40, speed_drop=0, congestion=0, ahead_congestion=0, incidents=[], deviated=False, deviation_m=0, heading_diff=0, gps_anomaly=False)
    return {**base, **k}


def test_cause_classification():
    c = classifier.classify(_f(speed=8, speed_drop=0.7, congestion=0.8, deviated=True))
    assert c["cause"] == "congestion" and c["confidence"] > 0.7
    assert classifier.classify(_f())["cause"] == "unknown" and classifier.classify(_f())["level"] == "Low"
    acc = dict(kind="accident", severity=0.9, active=True)
    assert classifier.classify(_f(incidents=[acc], speed_drop=0.5))["cause"] == "accident"
    assert classifier.classify(_f(gps_anomaly=True))["cause"] == "gps_anomaly"
    assert classifier.classify(_f(deviated=True, heading_diff=150))["cause"] == "wrong_turn"


def test_route_scoring_prefers_clear_route():
    a = [(12.95, 77.55 + i * 0.005) for i in range(10)]
    b = [(12.97, 77.55 + i * 0.005) for i in range(10)]
    incs = [dict(kind="accident", lat=12.95, lon=77.575, radius_m=600, severity=0.9, active=True)]
    r = dispatch.score_routes([dict(points=a, distance_m=5000, duration_s=600), dict(points=b, distance_m=5400, duration_s=660)], incs)
    assert r[0]["label"] == "B" and r[0]["recommended"] and r[0]["score"] < r[1]["score"]


def test_backup_selection_picks_closest_available():
    p = VehicleState("AMB-P"); p.lat, p.lon, p.delay_min = 12.92, 77.62, 14
    near, far, busy = VehicleState("AMB-N"), VehicleState("AMB-F"), VehicleState("AMB-B")
    for v, lat, lon, av in ((near, 12.93, 77.62, True), (far, 13.05, 77.55, True), (busy, 12.921, 77.62, False)):
        v.lat, v.lon, v.available, v.online = lat, lon, av, True
    rec = dispatch.select_backup(p, [p, near, far, busy], [])
    assert rec["backup_id"] == "AMB-N" and rec["distance_km"] < 3
    assert dispatch.select_backup(p, [p, busy], []) is None


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


H = {"X-API-Key": "test-key"}
PKT = dict(vehicle_id="AMB-777", latitude=12.97, longitude=77.59, speed=30, heading=90)


def test_telemetry_api(client):
    assert client.post("/api/telemetry", json=PKT).status_code == 401                          # no key
    assert client.post("/api/telemetry", json=PKT, headers=H).status_code == 404                # unregistered vehicle
    assert client.post("/api/vehicles", json={"id": "AMB-777"}, headers=H).status_code == 201
    assert client.post("/api/telemetry", json=PKT, headers=H).status_code == 200
    assert client.post("/api/telemetry", json={**PKT, "latitude": 999}, headers=H).status_code == 422
    v = client.get("/api/vehicles/AMB-777").json()
    assert v["lat"] == 12.97 and v["online"] and v["status"] == "available"
    assert client.get("/api/vehicles/AMB-777/telemetry").json()[0]["speed"] == 30
    assert client.get("/api/system/status").json()["status"] == "ok"


def test_websocket_pushes_updates(client):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert any(v["id"] == "AMB-777" for v in first["vehicles"])
        client.post("/api/telemetry", json={**PKT, "latitude": 12.97002}, headers=H)
        for _ in range(4):
            snap = ws.receive_json()
            if next(v for v in snap["vehicles"] if v["id"] == "AMB-777")["lat"] == 12.97002:
                return
        pytest.fail("WebSocket never delivered the updated position")
