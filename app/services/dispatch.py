from datetime import datetime
from app.core.config import cfg
from . import geo, traffic


def score_routes(routes, incs, now=None):
    """Emergency-priority route score (lower = better): time + congestion + incident risk + distance."""
    now = now or datetime.now()
    w, (_, mult), items = cfg("scoring"), traffic.period(now), []
    for i, r in enumerate(routes):
        rt = geo.Route(r["points"], r["duration_s"])
        samples = [rt.point_at(rt.length * k / 10)[:2] for k in range(11)]
        cong = sum(traffic.congestion_at(*p, incs, now) for p in samples) / len(samples)
        risk = min(1.0, sum(x["severity"] for x in incs if x.get("active", True) and
                            any(geo.haversine(*p, x["lat"], x["lon"]) < x["radius_m"] + 150 for p in samples)))
        eta = (r["duration_s"] * mult * (1 + 0.9 * cong) + risk * 300) / 60
        items.append(dict(label="ABCDEFG"[i], points=geo.simplify(r["points"], 80), distance_km=round(rt.length / 1000, 1),
                          eta_min=round(eta, 1), congestion=round(cong, 2), traffic=traffic.level(cong), risk=round(risk, 2),
                          source=r.get("source")))
    tmin, dmin = min(x["eta_min"] for x in items) or 1, min(x["distance_km"] for x in items) or 1
    for x in items:
        x["score"] = round(w["time"] * x["eta_min"] / tmin + w["congestion"] * x["congestion"] + w["incident_risk"] * x["risk"]
                           + w["distance"] * x["distance_km"] / dmin, 3)
    items.sort(key=lambda x: x["score"])
    for k, x in enumerate(items):
        x["recommended"] = k == 0
    return items


def select_backup(primary, vehicles, incs, now=None, delay_min=None):
    """Closest available, online vehicle by estimated response time. Recommendation for a human operator only."""
    now = now or datetime.now()
    _, mult = traffic.period(now)
    ff, rf = cfg("dispatch.free_flow_kmh"), cfg("dispatch.road_factor")
    best = None
    for v in vehicles:
        if v.id == primary.id or not (v.available and v.online and v.lat is not None):
            continue
        dist = geo.haversine(v.lat, v.lon, primary.lat, primary.lon) * rf
        cong = traffic.congestion_at(v.lat, v.lon, incs, now)
        mins = dist / 1000 / (ff / (mult * (1 + 0.8 * cong))) * 60
        cand = dict(backup_id=v.id, distance_km=round(dist / 1000, 1), response_min=round(mins), score=mins + 4 * cong)
        if best is None or cand["score"] < best["score"]:
            best = cand
    if not best:
        return None
    d = delay_min if delay_min is not None else primary.delay_min
    best.pop("score")
    best.update(primary_id=primary.id, delay_min=round(d, 1), basis="straight-line x road factor (estimate)",
                reason="Closest available emergency vehicle with lowest predicted response time.")
    return best
