"""Twilio Media Streams WebSocket client.

Connects to either a real Twilio Media Streams WebSocket or the call
simulator (same protocol). Bridges the WebSocket JSON messages to the
AudioPipeline.

Twilio Media Streams protocol (JSON over WebSocket):
    Server → Agent:
        connected  — initial handshake
        start      — stream metadata (callSid, encoding, etc.)
        media      — base64-encoded G.711 μ-law audio frame
        stop       — stream ended

    Agent → Server:
        media      — base64 audio to play on the call
        dtmf       — send DTMF digit (simulator extension)
        mark       — label a point in the audio stream
        clear      — clear queued outbound audio

See docs/TIER1_FEATURES.md §F2.
"""
from __future__ import annotations

import asyncio
import json

import websockets

from voice_agent.audio.pipeline import AudioPipeline
from voice_agent.logging import get_logger
from voice_agent.metrics import metrics

log = get_logger(__name__)


class MediaStreamClient:
    """WebSocket client for Twilio Media Streams / simulator.

    Manages the bidirectional audio connection. Feeds inbound audio
    to the AudioPipeline and reads outbound audio from it.
    """

    def __init__(self, ws_url: str, pipeline: AudioPipeline):
        self._ws_url = ws_url
        self._pipeline = pipeline
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._call_sid: str | None = None
        self._stream_sid: str | None = None
        self._running = False
        self._log = log.bind(component="media_stream")

    @property
    def call_sid(self) -> str | None:
        return self._call_sid

    @property
    def stream_sid(self) -> str | None:
        return self._stream_sid

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running

    async def connect(self) -> None:
        """Connect to the Media Streams WebSocket and wait for start event."""
        self._log.info("connecting", url=self._ws_url)
        self._ws = await websockets.connect(self._ws_url)
        self._running = True

        # Wait for connected + start events
        while True:
            raw = await self._ws.recv()
            msg = json.loads(raw)
            event = msg.get("event", "")

            if event == "connected":
                self._log.info("ws_connected", protocol=msg.get("protocol"))
            elif event == "start":
                start = msg.get("start", {})
                self._call_sid = start.get("callSid")
                self._stream_sid = msg.get("streamSid")
                self._log.info(
                    "stream_started",
                    call_sid=self._call_sid,
                    stream_sid=self._stream_sid,
                )
                break
            else:
                self._log.debug("unexpected_pre_start_event", event=event)

    async def run(self) -> None:
        """Run the bidirectional audio bridge.

        Starts two concurrent tasks:
        1. Inbound: read WebSocket → feed AudioPipeline
        2. Outbound: read AudioPipeline → send WebSocket

        Runs until the stream ends or disconnect() is called.
        """
        if not self._ws:
            raise RuntimeError("Call connect() first")

        inbound_task = asyncio.create_task(self._inbound_loop())
        outbound_task = asyncio.create_task(self._outbound_loop())

        try:
            # Wait for either task to finish (inbound ends on "stop" event)
            done, pending = await asyncio.wait(
                [inbound_task, outbound_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Cancel the other task
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            self._log.error("media_stream_error", error=str(e))
        finally:
            self._running = False

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._log.info("disconnected")

    async def send_dtmf(self, digit: str) -> None:
        """Send a DTMF digit over the WebSocket."""
        if not self._ws:
            return
        msg = json.dumps({
            "event": "dtmf",
            "streamSid": self._stream_sid,
            "dtmf": {"digit": digit},
        })
        await self._ws.send(msg)
        self._log.debug("dtmf_sent", digit=digit)

    async def clear_audio(self) -> None:
        """Clear any queued outbound audio (for barge-in)."""
        if not self._ws:
            return
        msg = json.dumps({
            "event": "clear",
            "streamSid": self._stream_sid,
        })
        await self._ws.send(msg)

    async def _inbound_loop(self) -> None:
        """Read inbound audio from WebSocket and feed to AudioPipeline."""
        frames = 0
        try:
            async for raw in self._ws:
                if not self._running:
                    break
                msg = json.loads(raw)
                event = msg.get("event", "")

                if event == "media":
                    payload = msg.get("media", {}).get("payload", "")
                    if payload:
                        await self._pipeline.feed_inbound(payload)
                        frames += 1
                elif event == "stop":
                    self._log.info("stream_stopped", inbound_frames=frames)
                    break
                elif event == "mark":
                    self._log.debug("mark_received", name=msg.get("mark", {}).get("name"))
        except websockets.ConnectionClosed:
            self._log.info("ws_closed", inbound_frames=frames)
        finally:
            self._pipeline.stop()
            metrics.inc("media_stream_inbound_frames", amount=frames)

    async def _outbound_loop(self) -> None:
        """Read outbound audio from AudioPipeline and send to WebSocket."""
        frames = 0
        try:
            async for b64_frame in self._pipeline.outbound_stream():
                if not self._running or not self._ws:
                    break
                msg = json.dumps({
                    "event": "media",
                    "streamSid": self._stream_sid,
                    "media": {"payload": b64_frame},
                })
                await self._ws.send(msg)
                frames += 1
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            metrics.inc("media_stream_outbound_frames", amount=frames)
