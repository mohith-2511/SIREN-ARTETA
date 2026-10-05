import logging
import httpx
from app.core.config import settings

log = logging.getLogger("bevims.explain")


def explain(s):
    p = []
    dv = s.dev
    if dv.get("deviated"):
        p.append(f"{s.id} deviated from its planned route by approximately {dv['distance_m']:.0f} meters.")
    if s.cause and s.cause["cause"] != "unknown":
        p.append(f"Probable cause: {s.cause['label']} (heuristic confidence {s.cause['confidence'] * 100:.0f}%, {s.cause['evidence']}). This is a prediction, not a confirmed fact.")
    elif s.cause:
        p.append("The cause could not be determined from the available evidence (confidence: Low).")
    if s.delay_min >= 1:
        p.append(f"The system predicts an additional delay of approximately {s.delay_min:.0f} minutes.")
    if s.best:
        cur = (s.current_eta - __import__("datetime").datetime.now()).total_seconds() / 60 if s.current_eta else None
        gain = f" and could reduce the estimated time by about {cur - s.best['eta_min']:.0f} minutes" if cur and cur - s.best['eta_min'] >= 1 else ""
        p.append(f"Alternative Route {s.best['label']} is recommended: {s.best['traffic'].lower()} predicted congestion, {s.best['eta_min']:.0f} min, {s.best['distance_km']} km{gain}.")
    if s.backup:
        b = s.backup
        p.append(f"{b['backup_id']} is the closest available backup vehicle (~{b['distance_km']} km, ~{b['response_min']} min estimated response) if additional emergency resources are required. Final decision rests with the control-room operator.")
    return " ".join(p)


async def polish(text):
    """Optional: rewrite the template text with an LLM via OpenRouter if OPENROUTER_API_KEY is set."""
    if not settings.OPENROUTER_API_KEY or not text:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post("https://openrouter.ai/api/v1/chat/completions",
                             headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                             json={"model": settings.LLM_MODEL, "messages": [
                                 {"role": "system", "content": "Rewrite this emergency-dispatch note concisely and clearly. Do not add facts or certainty."},
                                 {"role": "user", "content": text}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("LLM explanation unavailable (%s); using template text.", type(e).__name__)
        return None
