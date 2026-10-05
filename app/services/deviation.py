from app.core.config import settings
from . import geo


class DeviationDetector:
    """Compares live GPS against the planned polyline: perpendicular distance, time off-route, heading difference,
    and route divergence (distance actually travelled minus planned progress). Deviation fires only if the vehicle
    stays beyond DEVIATION_DISTANCE_THRESHOLD for DEVIATION_TIME_THRESHOLD seconds (filters GPS jitter)."""

    def __init__(self, dist_m=None, secs=None):
        self.dist_m = settings.DEVIATION_DISTANCE_THRESHOLD if dist_m is None else dist_m
        self.secs = settings.DEVIATION_TIME_THRESHOLD if secs is None else secs

    def evaluate(self, st, now):
        d, along, seg_h, near = st.route.nearest(st.lat, st.lon)
        if d > self.dist_m:
            st.off_since = st.off_since or now
        else:
            st.off_since = None
        off = (now - st.off_since) if st.off_since else 0.0
        if st.along0 is None:
            st.along0 = along
        hd = geo.angle_diff(st.heading, seg_h) if st.speed > 3 else 0.0
        div = max(0.0, st.travelled - max(along - st.along0, 0.0))
        st.dev = dict(distance_m=round(d, 1), off_seconds=round(off, 1), heading_diff=round(hd, 1),
                      deviated=bool(st.off_since and off >= self.secs), divergence_m=round(div, 1),
                      along_m=along, nearest=[near[0], near[1]])
        return st.dev
