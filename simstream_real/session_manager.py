"""In‑memory session store for the SimStream backend.

This module defines a very simple in‑memory session manager.  Each
session has a unique identifier, a simulator UDID and an associated
WebRTC peer connection.  Sessions expire after a configurable
timeout.  For simplicity the session IDs are random strings and not
cryptographically secure; use a secure random generator in
production.
"""
from __future__ import annotations

import asyncio
import os
import random
import string
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from aiortc import RTCPeerConnection  # type: ignore



def _random_session_id(length: int = 12) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


@dataclass
class Session:
    udid: str
    peer_connection: Optional[RTCPeerConnection] = None
    token: str = field(default_factory=lambda: _random_session_id(24))
    created_at: float = field(default_factory=time.time)
    expires_in: float = 60 * 60  # default TTL: 1 hour

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.expires_in


class SessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}
        # Launch a background task to clean up expired sessions.
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def create_session(self, udid: str, ttl: float = 3600) -> Session:
        session_id = _random_session_id(8)
        session = Session(udid=udid, expires_in=ttl)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        session = self.sessions.get(session_id)
        if session and not session.is_expired():
            return session
        # Expired or missing: delete it.
        if session:
            del self.sessions[session_id]
        return None

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired = [sid for sid, s in self.sessions.items() if s.is_expired()]
            for sid in expired:
                session = self.sessions.pop(sid)
                # Close peer connection if still open.
                if session.peer_connection:
                    try:
                        await session.peer_connection.close()
                    except Exception:
                        pass
