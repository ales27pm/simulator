"""Utilities for capturing frames from the iOS simulator.

The goal of this module is to provide a thin abstraction around the
``xcrun simctl`` command line tool that ships with Xcode.  It
implements a ``SimulatorCapture`` class capable of producing RGB
frames from a running simulator.  When running on a non‑macOS
environment or when ``simctl`` is unavailable, the capture falls back
to generating synthetic frames for demonstration purposes.

This module depends on Pillow and numpy for image decoding and
manipulation.
"""
from __future__ import annotations

import asyncio
import os
import platform
import random
import string
import subprocess
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Tuple

import numpy as np  # type: ignore
from PIL import Image  # type: ignore
from io import BytesIO


class SimulatorCapture:
    """Helper for capturing frames from an iOS Simulator.

    Instances of this class are bound to a particular simulator UDID.
    On macOS the ``capture_frame`` method invokes ``xcrun simctl io
    {udid} screenshot -`` which writes a PNG to stdout.  The PNG is
    decoded with Pillow and converted to a NumPy RGB array.

    If running on a platform other than Darwin (macOS) or if ``simctl``
    cannot be found, the implementation will instead produce a
    synthetic colour pattern each time it is called.  This allows
    developers to exercise the rest of the pipeline on Linux.
    """

    def __init__(self, udid: str, width: Optional[int] = None, height: Optional[int] = None) -> None:
        self.udid = udid
        self.width = width
        self.height = height
        self._on_macos = platform.system() == "Darwin"
        self._simctl_path = self._find_simctl() if self._on_macos else None

    @staticmethod
    def _find_simctl() -> Optional[str]:
        """Attempt to locate the simctl binary on macOS.

        Returns the path to simctl if found, otherwise None.
        """
        for p in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(p, "simctl")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        # Xcode usually installs simctl in /usr/bin/xcrun, but using the
        # wrapper ensures the correct developer toolchain is selected.
        return None

    async def capture_frame(self) -> np.ndarray:
        """Capture a single frame as a NumPy RGB array.

        This coroutine returns immediately with a synthetic frame when
        ``simctl`` is unavailable.  On macOS it spawns the process
        ``xcrun simctl io {udid} screenshot -`` and reads the PNG
        data from stdout.  The PNG is decoded into an RGB array.
        """
        if not self._on_macos or self._simctl_path is None:
            return self._generate_test_pattern()
        # Use the xcrun wrapper to ensure the right developer tools.
        proc = await asyncio.create_subprocess_exec(
            "xcrun",
            "simctl",
            "io",
            self.udid,
            "screenshot",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate()
        finally:
            if proc.returncode is None:
                proc.kill()
        if proc.returncode != 0:
            # In case of failure, fall back to test pattern.
            return self._generate_test_pattern()
        # Decode PNG.
        img = Image.open(BytesIO(stdout))  # type: ignore
        img = img.convert("RGB")
        arr = np.array(img)
        if self.width is not None and self.height is not None:
            if arr.shape[1] != self.width or arr.shape[0] != self.height:
                img = img.resize((self.width, self.height))
                arr = np.array(img)
        return arr

    def _generate_test_pattern(self) -> np.ndarray:
        """Generate a synthetic test pattern for environments without simctl."""
        # Create a simple colour gradient with random noise.
        width = self.width or 640
        height = self.height or 480
        base_color = np.array([
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
        ], dtype=np.uint8)
        gradient = np.linspace(0, 1, width, dtype=np.float32)
        row = (base_color * gradient[:, None]).astype(np.uint8)
        frame = np.repeat(row[None, :, :], height, axis=0)
        noise = np.random.randint(0, 30, (height, width, 3), dtype=np.uint8)
        return frame + noise
