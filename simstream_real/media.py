"""Media streaming helpers for the SimStream backend.

This module provides a custom ``VideoStreamTrack`` implementation
compatible with the ``aiortc`` library.  The ``SimulatorVideoTrack``
class pulls frames from a ``SimulatorCapture`` instance and yields
``av.VideoFrame`` objects.  It uses an internal FPS throttle to
prevent spamming the event loop with captures faster than the
specified frame rate.

The module also exposes ``create_peer_connection`` which creates a
``RTCPeerConnection``, attaches the video track and responds to an
SDP offer.  Note that ICE server configuration is intentionally
minimal for demonstration purposes.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple

import av  # type: ignore
from aiortc import RTCPeerConnection, RTCSessionDescription  # type: ignore
from aiortc.contrib.media import MediaStreamTrack  # type: ignore

from .simulator_capture import SimulatorCapture


class SimulatorVideoTrack(MediaStreamTrack):
    """A VideoStreamTrack that streams frames from a SimulatorCapture."""

    kind = "video"

    def __init__(self, capture: SimulatorCapture, fps: float = 15.0) -> None:
        super().__init__()  # type: ignore
        self._capture = capture
        self._fps = fps
        self._next_frame_time: float = 0.0

    async def recv(self) -> av.VideoFrame:  # type: ignore
        """Capture the next frame and return an av.VideoFrame."""
        # Throttle to the desired frame rate.
        now = asyncio.get_event_loop().time()
        wait = self._next_frame_time - now
        if wait > 0:
            await asyncio.sleep(wait)
        frame_array = await self._capture.capture_frame()
        # Convert numpy array to VideoFrame.
        # frame_array is shape (height, width, 3).
        height, width, _ = frame_array.shape
        video_frame = av.VideoFrame.from_ndarray(frame_array, format="rgb24")
        video_frame.pts = None
        video_frame.time_base = None
        # Update next frame time.
        self._next_frame_time = now + 1.0 / self._fps
        return video_frame


async def create_peer_connection(
    capture: SimulatorCapture,
    offer_sdp: str,
    offer_type: str,
    ice_servers: Optional[list[dict]] = None,
) -> Tuple[RTCPeerConnection, RTCSessionDescription]:
    """Create a peer connection, handle an offer, attach a video track and return an answer.

    :param capture: A SimulatorCapture instance bound to a simulator UDID.
    :param offer_sdp: The remote SDP offer string.
    :param offer_type: The type of the remote session description (usually "offer").
    :param ice_servers: Optional list of ICE server configurations.  Each
        entry should be a dict with at least a ``urls`` key.
    :returns: A tuple of (peer_connection, answer) where ``answer`` is an
        ``RTCSessionDescription``.
    """
    pc = RTCPeerConnection(configuration={"iceServers": ice_servers or []})
    video_track = SimulatorVideoTrack(capture)
    pc.addTrack(video_track)

    @pc.on("connectionstatechange")
    async def on_state_change() -> None:
        # Close the peer connection when it goes to failed/closed.
        if pc.connectionState in ("failed", "closed"):
            await pc.close()

    # Set remote description and create answer.
    offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return pc, pc.localDescription
