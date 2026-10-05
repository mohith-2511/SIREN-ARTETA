import time, math, logging
import httpx
from app.core.config import settings
from . import geo

log = logging.getLogger("bevims.routing")
_cache, _down_until = {}, 0.0
state = {"provider": settings.ROUTING_PROVIDER, "last_source": None, "message": ""}


def _bez(a, b, off, n=45):
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    dy, dx = b[0] - a[0], b[1] - a[1]
    c = (mid[0] - dx * off, mid[1] + dy * off)
    out = []
    for i in range(n + 1):
        t = i / n
        out.append(((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1]))
    return out


def _fallback(a, b, alts):
    outs = []
    for off in ((0.04, 0.16, -0.14) if alts else (0.04,)):
        pts = _bez(a, b, off)
        L = geo.polyline_len(pts) * 1.2
        outs.append({"points": pts, "distance_m": L, "duration_s": L / (35 / 3.6), "source": "fallback"})
    return outs


async def fetch_routes(a, b, alts=True):
    """a, b = (lat, lon). Returns [{points, distance_m, duration_s, source}] - OSRM, else straight-ish fallback estimate."""
    global _down_until
    key = (round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3), alts)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    if settings.ROUTING_PROVIDER == "osrm" and time.time() > _down_until:
        try:
            url = f"{settings.OSRM_URL}/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}"
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(url, params={"overview": "full", "geometries": "geojson", "alternatives": "true" if alts else "false"})
            r.raise_for_status()
            out = [{"points": [(y, x) for x, y in rt["geometry"]["coordinates"]], "distance_m": rt["distance"],
                    "duration_s": rt["duration"], "source": "osrm"} for rt in r.json()["routes"]]
            if out:
                state.update(last_source="osrm", message="")
                _cache[key] = (time.time(), out)
                return out
        except Exception as e:
            _down_until = time.time() + 60
            log.warning("Routing service unavailable (%s). Using fallback route estimation.", type(e).__name__)
    state.update(last_source="fallback", message="Routing service unavailable. Using fallback route estimation.")
    out = _fallback(a, b, alts)
    _cache[key] = (time.time() - 240, out)
    return out
