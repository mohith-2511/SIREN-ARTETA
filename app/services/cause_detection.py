LABELS = {"congestion": "Heavy Traffic", "accident": "Accident / Road Incident", "road_closure": "Road Closure",
          "wrong_turn": "Wrong Turn", "gps_anomaly": "GPS Anomaly", "driver_rerouting": "Driver Rerouting", "unknown": "Unknown"}


class RuleBasedClassifier:
    """Rule-based cause estimation. classify(features) -> dict is the interface an ML model can later replace.
    'confidence' is a heuristic score, NOT a calibrated probability."""

    def classify(self, f):
        sc, ev = {}, {}
        cong = max(f["congestion"], f["ahead_congestion"])
        acc = [i for i in f["incidents"] if i["kind"] == "accident"]
        clo = [i for i in f["incidents"] if i["kind"] == "closure"]
        if f["gps_anomaly"]:
            sc["gps_anomaly"] = 0.85; ev["gps_anomaly"] = "implausible position jump between fixes"
        if acc:
            sc["accident"] = min(0.95, 0.55 + 0.4 * max(i["severity"] for i in acc) + (0.05 if f["speed_drop"] > 0.3 else 0))
            ev["accident"] = "active accident incident near vehicle/route"
        if clo:
            sc["road_closure"] = min(0.95, 0.5 + 0.35 * max(i["severity"] for i in clo) + (0.1 if f["deviated"] else 0))
            ev["road_closure"] = "road closure reported nearby"
        if cong > 0.4 and (f["speed_drop"] > 0.25 or f["speed"] < 15):
            sc["congestion"] = min(0.95, 0.4 + 0.35 * cong + 0.25 * min(f["speed_drop"], 1) + (0.1 if f["deviated"] else 0))
            ev["congestion"] = f"congestion index {cong:.2f} with speed drop {f['speed_drop'] * 100:.0f}%"
        if f["deviated"] and f["speed_drop"] <= 0.25 and cong < 0.4:
            if f["heading_diff"] > 100:
                sc["wrong_turn"] = 0.6; ev["wrong_turn"] = "heading opposes route, normal speed, no congestion"
            else:
                sc["driver_rerouting"] = 0.5; ev["driver_rerouting"] = "off-route at normal speed, no congestion evidence"
        if not sc or max(sc.values()) < 0.35:
            return dict(cause="unknown", label="Unknown", confidence=0.0, level="Low", evidence="insufficient evidence")
        c = max(sc, key=sc.get)
        return dict(cause=c, label=LABELS[c], confidence=round(sc[c], 2), level="High" if sc[c] > 0.75 else "Medium",
                    evidence=ev[c])


classifier = RuleBasedClassifier()
