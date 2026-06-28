SimStream Real Backend
======================

This directory contains a minimalist proof‑of‑concept implementation of a
"real" iOS simulator streaming backend.  The goal is to show how
simulator video frames can be captured, encoded and delivered to a WebRTC
client using Python.  The implementation is intentionally bare bones
and makes a number of simplifying assumptions, but it demonstrates
the core ideas needed to build a production system.

Overview
--------

* ``backend.py`` – entry point for the FastAPI application.  It
  exposes health checks, simulator enumeration, session creation and
  WebRTC signalling endpoints.
* ``simulator_capture.py`` – helpers for capturing frames from a
  running simulator.  It relies on the ``xcrun simctl io`` commands
  available on macOS to grab screenshots in PNG format and decode
  them into raw RGB frames.  On non‑macOS platforms it falls back to
  a dummy generator that yields coloured test patterns.
* ``media.py`` – implements a custom ``aiortc`` ``MediaStreamTrack``
  subclass that repeatedly calls ``SimulatorCapture.capture_frame``
  and yields the images as video frames.  It also contains
  ``create_peer_connection`` which handles an incoming SDP offer and
  returns a matching answer.
* ``control.py`` – provides an async interface for sending control
  events (tap, swipe, text, etc.) to the simulator using ``xcrun`` or
  ``idb``.  These commands are executed with ``asyncio.create_subprocess_exec``
  to avoid blocking the event loop.
* ``session_manager.py`` – minimal in‑memory session store with
  expiration.  Each session holds the selected simulator UDID and
  the peer connection associated with it.  A production system
  would persist sessions in a database and implement proper
  authentication.

Prerequisites
-------------

The code in this proof of concept depends on a few Python packages
which are not part of the standard library.  You can install them
with pip:

```
pip install fastapi uvicorn aiortc pillow numpy
```

On a macOS host you must also have Xcode installed so that the
``xcrun simctl`` command is available.  On Linux, the capture will
fall back to dummy frames.  At runtime the backend must be able to
spawn subprocesses and read from standard output.

Usage
-----

To run the development server, set up a virtual environment, install
the dependencies, then launch the app:

```
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn aiortc pillow numpy
uvicorn simstream_real.backend:app --reload
```

Once running, you can browse the automatically generated
OpenAPI documentation at ``http://localhost:8000/docs``.  From there
you can list simulators, create a session, and exchange WebRTC offers
and answers.

Important Notes
---------------

1. This proof of concept is not secure.  It uses a hardcoded shared
   secret for simple authentication and stores sessions in memory.
   In a real deployment you must implement proper authentication,
   authorisation, and secure key handling.
2. The capture loop uses ``asyncio.sleep`` to throttle the frame
   rate.  For higher performance you should integrate with a native
   AVFoundation capture API or use ``simctl io recordVideo`` in
   conjunction with a video decoder.
3. The WebRTC implementation does not support TURN or ICE servers.
   To make this work on the open internet you need to configure
   STUN/TURN servers and gather ICE candidates accordingly.