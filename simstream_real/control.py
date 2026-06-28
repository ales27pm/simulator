"""Simulated control event executor for iOS simulators.

This module defines an async ``SimulatorController`` class for
sending user input events to a running simulator.  It uses either
``idb`` (the Facebook IDB companion tool) when available or falls
back to ``xcrun simctl``.  Each method returns when the command
completes.  Errors are swallowed and logged to stderr for now.

In a production system you would handle errors more carefully and
support additional event types.
"""
from __future__ import annotations

import asyncio
import os
import platform
import shlex
from dataclasses import dataclass
from typing import Optional



def _command_exists(cmd: str) -> bool:
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path, cmd)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return True
    return False


@dataclass
class SimulatorController:
    udid: str
    use_idb: bool = False

    def __post_init__(self) -> None:
        # Determine whether idb is available.
        if _command_exists("idb"):
            self.use_idb = True
        elif _command_exists("idb_companion"):
            self.use_idb = True

    async def _run(self, *args: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        # For debugging: print stderr if error.
        if proc.returncode != 0:
            try:
                err = stderr.decode().strip()
            except Exception:
                err = str(stderr)
            print(f"[control] command failed: {' '.join(args)} -> {err}", flush=True)

    async def tap(self, x: float, y: float, width: int, height: int) -> None:
        """Inject a tap at the given normalized coordinates.

        :param x: normalized x coordinate (0..1)
        :param y: normalized y coordinate (0..1)
        :param width: viewport width in pixels
        :param height: viewport height in pixels
        """
        # Convert normalized to absolute coordinates.
        abs_x = int(x * width)
        abs_y = int(y * height)
        if self.use_idb:
            await self._run(
                "idb",
                "ui",
                "tap",
                str(abs_x),
                str(abs_y),
                "--udid",
                self.udid,
            )
        else:
            await self._run(
                "xcrun",
                "simctl",
                "io",
                self.udid,
                "tap",
                str(abs_x),
                str(abs_y),
            )

    async def swipe(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int,
        width: int,
        height: int,
    ) -> None:
        """Inject a swipe from (x1,y1) to (x2,y2)."""
        abs_x1 = int(x1 * width)
        abs_y1 = int(y1 * height)
        abs_x2 = int(x2 * width)
        abs_y2 = int(y2 * height)
        if self.use_idb:
            await self._run(
                "idb",
                "ui",
                "swipe",
                str(abs_x1),
                str(abs_y1),
                str(abs_x2),
                str(abs_y2),
                "--duration",
                str(duration_ms / 1000.0),
                "--udid",
                self.udid,
            )
        else:
            await self._run(
                "xcrun",
                "simctl",
                "io",
                self.udid,
                "swipe",
                str(abs_x1),
                str(abs_y1),
                str(abs_x2),
                str(abs_y2),
                str(duration_ms / 1000.0),
            )

    async def text(self, text: str) -> None:
        """Inject a string of text via the keyboard."""
        if self.use_idb:
            await self._run(
                "idb",
                "ui",
                "text",
                text,
                "--udid",
                self.udid,
            )
        else:
            await self._run(
                "xcrun",
                "simctl",
                "io",
                self.udid,
                "keyboard",
                text,
            )

    async def key(self, keycode: str) -> None:
        """Inject a key press (single key) into the simulator."""
        if self.use_idb:
            await self._run(
                "idb",
                "ui",
                "key",
                keycode,
                "--udid",
                self.udid,
            )
        else:
            await self._run(
                "xcrun",
                "simctl",
                "io",
                self.udid,
                "keyboard",
                keycode,
            )
