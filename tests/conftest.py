import os, tempfile, pathlib
_tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite:///{pathlib.Path(_tmp, 't.db').as_posix()}", SIMULATION_MODE="false", MQTT_ENABLED="false",
                  TELEMETRY_API_KEY="test-key", DEMO_AUTOPLAY="false", ROUTING_PROVIDER="none")
