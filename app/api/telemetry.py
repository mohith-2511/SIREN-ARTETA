import json, logging, math
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

log = logging.getLogger("bevims.mqtt")
ID_PATTERN = r"^[A-Za-z0-9_-]{2,32}$"


class TelemetryIn(BaseModel):
    """EVT - Emergency Vehicle Transponder packet."""
    vehicle_id: str = Field(pattern=ID_PATTERN)
    timestamp: Optional[datetime] = None
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    speed: float = Field(0, ge=0, le=250, allow_inf_nan=False)
    heading: float = Field(0, ge=0, le=360, allow_inf_nan=False)
    emergency: bool = False
    destination: Optional[str] = Field(None, max_length=80)
    route_id: Optional[str] = Field(None, max_length=64)

    @field_validator("destination", "route_id")
    @classmethod
    def clean(cls, v):
        return " ".join(v.replace("<", "").replace(">", "").split()) or None if v else None

    @model_validator(mode="after")
    def not_null_island(self):
        if abs(self.latitude) < 0.001 and abs(self.longitude) < 0.001:
            raise ValueError("GPS fix (0,0) rejected as invalid")
        return self


class MqttBridge:
    connected = False

    def __init__(self):
        self.client = None

    def start(self, loop, handler, settings):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            log.error("paho-mqtt not installed - MQTT disabled"); return
        if not settings.MQTT_BROKER:
            log.warning("MQTT_ENABLED=true but MQTT_BROKER is empty - set it in .env. MQTT input disabled."); return
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            c = mqtt.Client()
        if settings.MQTT_USERNAME:
            c.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

        def on_connect(client, *a):
            self.connected = True; client.subscribe("ambulance/+/telemetry"); log.info("MQTT connected to %s", settings.MQTT_BROKER)

        def on_disconnect(*a):
            self.connected = False; log.warning("MQTT disconnected - will retry")

        def on_message(client, userdata, msg):
            try:
                data = json.loads(msg.payload)
                data["vehicle_id"] = msg.topic.split("/")[1]          # topic is authoritative
                t = TelemetryIn(**data)
            except Exception as e:
                log.warning("Rejected malformed MQTT telemetry on %s: %s", msg.topic, str(e)[:120]); return

            def go():
                try:
                    handler(t)
                except KeyError:
                    log.warning("Telemetry from unregistered vehicle %s rejected", t.vehicle_id)
            loop.call_soon_threadsafe(go)
        c.on_connect, c.on_disconnect, c.on_message = on_connect, on_disconnect, on_message
        try:
            c.connect_async(settings.MQTT_BROKER, settings.MQTT_PORT); c.loop_start(); self.client = c
        except Exception as e:
            log.error("MQTT unavailable (%s) - continuing without it", e)

    def stop(self):
        if self.client:
            self.client.loop_stop(); self.client.disconnect()


mqtt_bridge = MqttBridge()
