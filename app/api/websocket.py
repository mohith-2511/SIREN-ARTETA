import asyncio, json, logging
from fastapi import WebSocket, WebSocketDisconnect
from app.core.config import settings
from app.services.tracking import engine

log = logging.getLogger("bevims.ws")


class Manager:
    def __init__(self):
        self.clients = set()

    async def connect(self, ws: WebSocket):
        await ws.accept(); self.clients.add(ws)
        await ws.send_text(json.dumps(engine.snapshot(len(self.clients)), default=str))

    def drop(self, ws):
        self.clients.discard(ws)

    async def broadcast_loop(self):
        while True:
            try:
                await asyncio.sleep(settings.WEBSOCKET_UPDATE_INTERVAL)
                engine.monitor()
                if self.clients:
                    msg = json.dumps(engine.snapshot(len(self.clients)), default=str)
                    for ws in list(self.clients):
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            self.drop(ws)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("broadcast loop error (continuing)")


manager = Manager()


async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        manager.drop(ws)
