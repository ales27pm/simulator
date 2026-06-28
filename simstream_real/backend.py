"""FastAPI application entry point for the SimStream real backend.

This module wires together the simulator capture, media streaming,
control handling and session management to provide a minimal working
backend.  It exposes a REST and WebSocket API for listing
simulators, creating sessions, exchanging WebRTC SDP offers and
answers, and sending control events via WebSocket.

The API is intentionally simplistic and makes no attempt to be
complete or secure.  It uses a shared secret for basic auth and
stores sessions in memory.  It is meant as a starting point for
experimentation rather than production use.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .simulator_capture import SimulatorCapture
from .media import create_peer_connection
from .control import SimulatorController
from .session_manager import SessionManager, Session

# Shared secret for simple API authentication.  In production read this from
# an environment variable or secrets store.
API_SECRET = os.environ.get("SIMSTREAM_SHARED_SECRET", "change-me-dev-secret")


app = FastAPI(title="SimStream Real Backend")
session_manager = SessionManager()


def verify_secret(secret_header: str = Depends(lambda: None)) -> None:
    """Dependency that checks the shared secret in the request header."""
    # The header will be injected by FastAPI with a default name based on the
    # parameter name.  Use a custom dependency to read from X-SimStream-Secret.
    # In a real app you would integrate proper authentication.
    # Provided for route functions that expect a `secret_header` string.
    return None


@app.middleware("http")
async def check_secret(request, call_next):  # type: ignore
    # Simple shared-secret auth on all routes except docs/openapi.
    allowed_paths = {"/openapi.json", "/docs", "/docs/", "/redoc", "/health"}
    if request.url.path not in allowed_paths:
        secret = request.headers.get("X-SimStream-Secret")
        if secret != API_SECRET:
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


def _list_simulators() -> List[Dict[str, Any]]:
    """Return a list of available simulators.

    On macOS this parses ``xcrun simctl list devices available`` to
    discover booted or available devices.  On other platforms it
    returns a dummy list for testing.
    """
    if os.uname().sysname == "Darwin":
        try:
            import subprocess  # deferred import

            output = subprocess.check_output(["xcrun", "simctl", "list", "devices", "--json"])
            devices_json = json.loads(output.decode())
            simulators: List[Dict[str, Any]] = []
            for runtime_devices in devices_json.get("devices", {}).values():
                for dev in runtime_devices:
                    # Only include available devices (not unavailable)
                    if not dev.get("isAvailable"):
                        continue
                    simulators.append({
                        "udid": dev.get("udid"),
                        "name": dev.get("name"),
                        "state": dev.get("state"),
                    })
            return simulators
        except Exception:
            pass
    # Fallback: return a dummy simulator for demonstration on non‑macOS.
    return [{"udid": "DUMMY-UDID", "name": "Dummy Simulator", "state": "Booted"}]


@app.get("/simulators")
async def get_simulators() -> List[Dict[str, Any]]:
    return _list_simulators()


class SessionCreateRequest(BaseModel):
    udid: str
    ttl: Optional[int] = 3600


class SessionCreateResponse(BaseModel):
    session_id: str
    token: str
    udid: str


@app.post("/sessions", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest) -> Any:
    session = session_manager.create_session(req.udid, ttl=req.ttl or 3600)
    return SessionCreateResponse(session_id=[k for k, v in session_manager.sessions.items() if v is session][0], token=session.token, udid=session.udid)


class OfferRequest(BaseModel):
    sdp: str
    type: str


class AnswerResponse(BaseModel):
    sdp: str
    type: str


@app.post("/sessions/{session_id}/offer", response_model=AnswerResponse)
async def handle_offer(session_id: str, offer: OfferRequest) -> Any:
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found or expired")
    # Create capture and WebRTC peer connection.
    capture = SimulatorCapture(session.udid)
    pc, answer = await create_peer_connection(capture, offer.sdp, offer.type)
    session.peer_connection = pc
    return AnswerResponse(sdp=answer.sdp, type=answer.type)


async def _authorize_ws(websocket: WebSocket, session: Session) -> None:
    """Verify the Authorization header on the WebSocket connection."""
    auth_header = websocket.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    token = auth_header.removeprefix("Bearer ").strip()
    if token != session.token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return


@app.websocket("/sessions/{session_id}/control")
async def control_ws(websocket: WebSocket, session_id: str) -> None:
    session = session_manager.get_session(session_id)
    if not session:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    # Authorise using token in Authorization header.
    await _authorize_ws(websocket, session)
    # Create controller for this session's UDID.
    controller = SimulatorController(udid=session.udid)
    try:
        while True:
            msg = await websocket.receive_json()
            event_type = msg.get("type")
            if event_type == "tap":
                x = msg.get("x", 0.5)
                y = msg.get("y", 0.5)
                width = msg.get("viewport_width", 390)
                height = msg.get("viewport_height", 844)
                await controller.tap(float(x), float(y), int(width), int(height))
            elif event_type == "swipe":
                await controller.swipe(
                    float(msg.get("x", 0.5)),
                    float(msg.get("y", 0.5)),
                    float(msg.get("x2", 0.5)),
                    float(msg.get("y2", 0.5)),
                    int(msg.get("duration_ms", 300)),
                    int(msg.get("viewport_width", 390)),
                    int(msg.get("viewport_height", 844)),
                )
            elif event_type == "text":
                text = msg.get("text", "")
                await controller.text(text)
            elif event_type == "key":
                keycode = msg.get("key")
                if keycode:
                    await controller.key(keycode)
            else:
                # Unknown event; ignore.
                continue
    except WebSocketDisconnect:
        pass
