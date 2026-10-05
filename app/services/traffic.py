"""Bengaluru traffic model. Time-of-day multipliers are SIMULATED (config.yaml), not measured data."""
from datetime import datetime
from app.core.config import cfg
from . import geo


def period(now=None):
    h = (now or datetime.now()).hour
    t = cfg("traffic")
    for name in ("morning_peak", "afternoon", "evening_peak"):
        p = t.get(name, {})
        if p.get("start", 99) <= h < p.get("end", -1):
            return name, float(p.get("multiplier", 1.0))
    return "night", float(t.get("night", {}).get("multiplier", 0.8))


def congestion_at(lat, lon, incs, now=None):
    """0..1 congestion index = time-of-day component + nearby incident influence (simulated/operator data)."""
    c = max(0.0, period(now)[1] - 1.0) * 0.4
    for i in incs:
        if not i.get("active", True):
            continue
        d = geo.haversine(lat, lon, i["lat"], i["lon"])
        if d < i["radius_m"]:
            c += i["severity"] * (1 - d / i["radius_m"]) * (1.0 if i["kind"] == "congestion" else 0.8)
    return min(c, 1.0)


def ahead_congestion(route, along, incs, span=2500, now=None):
    return max(congestion_at(*route.point_at(min(along + span * k / 8, route.length))[:2], incs, now) for k in range(9))


def nearby_incidents(lat, lon, incs, radius=900):
    return [i for i in incs if i.get("active", True) and geo.haversine(lat, lon, i["lat"], i["lon"]) <= radius + i["radius_m"] * 0.3]


def level(c):
    return "HIGH" if c > 0.6 else "MEDIUM" if c > 0.3 else "LOW"
