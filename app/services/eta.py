import statistics
from datetime import datetime
from . import traffic


class EtaPredictor:
    """Heuristic ETA model. predict() is the stable interface - a trained ML model can replace this class later."""

    def predict(self, remaining_m, speed_kmh, recent_speeds, congestion=0.0, route_kmh=35.0, now=None):
        _, mult = traffic.period(now or datetime.now())
        free = route_kmh / mult / (1 + 0.5 * congestion)         # time-of-day + congestion adjusted free-flow
        hist = statistics.mean(recent_speeds) if recent_speeds else speed_kmh
        eff = 0.5 * speed_kmh + 0.3 * hist + 0.2 * free
        return remaining_m / (max(eff, 3.0) / 3.6)


predictor = EtaPredictor()
