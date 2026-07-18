"""FastAPI app for the Retail CEO Office (bench-backed, scripted-only).

Single-process pattern (mirrors the SimMart Office): serves the prebuilt React
SPA at ``/`` + ``/assets`` and the live-run API under ``/api/*``.

Note on OpenEnv: the ``retailceo-bench`` codebase does not ship an OpenEnv-style
server/app (no ``server/app.py``, no ``openenv`` dependency), so there is no env
server to mount under a sub-path. The Office ``/api/*`` + SPA is the surface.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .runner import stream_run
from .schemas import RunConfig, RunCreated, RunState


class RunRecord:
    def __init__(self, run_id: str, config: RunConfig):
        self.run_id = run_id
        self.config = config
        self.status = "created"
        self.events: List[Dict[str, Any]] = []

    @property
    def latest_event(self) -> Optional[Dict[str, Any]]:
        return self.events[-1] if self.events else None

    def append(self, event: Dict[str, Any]) -> None:
        self.events.append(event)
        if len(self.events) > 200:
            self.events = self.events[-200:]
        if event["type"] == "run_started":
            self.status = "running"
        elif event["type"] == "run_completed":
            self.status = "completed"
        elif event["type"] == "run_failed":
            self.status = "failed"

    def model(self) -> RunState:
        return RunState(
            run_id=self.run_id,
            status=self.status,
            config=self.config,
            latest_event=self.latest_event,
            events=self.events,
        )


RUNS: Dict[str, RunRecord] = {}

app = FastAPI(title="Retail CEO Office", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/runs", response_model=RunCreated)
def create_run(config: RunConfig) -> RunCreated:
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = RunRecord(run_id, config)
    return RunCreated(run_id=run_id, status="created", config=config)


@app.get("/api/runs/{run_id}", response_model=RunState)
def get_run(run_id: str) -> RunState:
    record = RUNS.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model()


@app.websocket("/api/runs/{run_id}/stream")
async def stream_run_socket(websocket: WebSocket, run_id: str) -> None:
    record = RUNS.get(run_id)
    if record is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    try:
        async for event in stream_run(run_id, record.config):
            record.append(event)
            await websocket.send_json(event)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 - surface any run failure to the UI
        event = {
            "type": "run_failed",
            "run_id": run_id,
            "payload": {
                "error": type(exc).__name__,
                "message": str(exc),
            },
        }
        record.append(event)
        try:
            await websocket.send_json(event)
        except Exception:
            pass


FRONTEND_DIST = Path(__file__).resolve().parents[1] / "office" / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="office-assets",
    )

    @app.get("/")
    def frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")


def main(host: str = "0.0.0.0", port: int = 7860) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
