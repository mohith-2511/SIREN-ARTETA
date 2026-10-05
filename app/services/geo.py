import math, bisect

R = 6371000.0


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_diff(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def polyline_len(pts):
    return sum(haversine(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1))


def simplify(pts, n=120):
    k = max(1, len(pts) // n)
    out = [list(p) for p in pts[::k]]
    if list(pts[-1]) != out[-1]:
        out.append(list(pts[-1]))
    return out


LANDMARKS = [("Electronic City", 12.8452, 77.6602), ("Silk Board", 12.9177, 77.6233), ("Koramangala", 12.9352, 77.6245),
             ("Indiranagar", 12.9784, 77.6408), ("Whitefield", 12.9698, 77.7500), ("Marathahalli", 12.9591, 77.6974),
             ("KR Puram", 13.0043, 77.6957), ("Hebbal", 13.0358, 77.5970), ("Yeshwanthpur", 13.0285, 77.5400),
             ("Majestic", 12.9767, 77.5713), ("MG Road", 12.9756, 77.6066), ("HSR Layout", 12.9116, 77.6474),
             ("Domlur", 12.9609, 77.6387), ("Old Airport Road", 12.9600, 77.6550), ("Bommanahalli", 12.9081, 77.6238),
             ("Victoria Hospital area", 12.9634, 77.5755), ("Jayanagar", 12.9308, 77.5838), ("Malleshwaram", 13.0035, 77.5643)]


def nearest_landmark(lat, lon):
    n, la, lo = min(LANDMARKS, key=lambda l: haversine(lat, lon, l[1], l[2]))
    d = haversine(lat, lon, la, lo)
    return f"Near {n}" if d < 1500 else f"{d / 1000:.1f} km from {n}"


class Route:
    def __init__(self, pts, duration_s=None):
        self.pts = [(float(a), float(b)) for a, b in pts]
        self.cum = [0.0]
        for i in range(1, len(self.pts)):
            self.cum.append(self.cum[-1] + haversine(*self.pts[i - 1], *self.pts[i]))
        self.length = self.cum[-1]
        self.duration = duration_s or max(self.length, 1) / (35 / 3.6)

    def point_at(self, d):
        d = max(0.0, min(d, self.length))
        i = min(bisect.bisect_right(self.cum, d) - 1, len(self.pts) - 2)
        seg = self.cum[i + 1] - self.cum[i]
        t = (d - self.cum[i]) / seg if seg > 0 else 0
        (a, b), (c, e) = self.pts[i], self.pts[i + 1]
        return a + (c - a) * t, b + (e - b) * t, bearing(a, b, c, e)

    def nearest(self, lat, lon):
        """-> (distance_m to route, metres along route, route heading there, nearest (lat, lon))"""
        k, mm = math.cos(math.radians(lat)) * 111320, 110540
        best = (1e18, 0, 0, 0)
        for i in range(len(self.pts) - 1):
            ax, ay = (self.pts[i][1] - lon) * k, (self.pts[i][0] - lat) * mm
            bx, by = (self.pts[i + 1][1] - lon) * k, (self.pts[i + 1][0] - lat) * mm
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = 0 if L2 == 0 else max(0, min(1, -(ax * dx + ay * dy) / L2))
            px, py = ax + t * dx, ay + t * dy
            d = math.hypot(px, py)
            if d < best[0]:
                best = (d, i, t, (lat + py / mm, lon + px / k))
        d, i, t, near = best
        along = self.cum[i] + t * (self.cum[i + 1] - self.cum[i])
        return d, along, bearing(*self.pts[i], *self.pts[i + 1]), near
