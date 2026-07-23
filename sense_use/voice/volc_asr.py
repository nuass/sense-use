"""Volc streaming ASR — WebSocket client.

Endpoint: ``wss://openspeech.bytedance.com/api/v3/sauc/bigmodel``.

Reads credentials from env:
- ``VOLC_APP_ID`` — application id
- ``VOLC_ACCESS_TOKEN`` — the 32-char permanent access token from the
  ApplicationCredentials endpoint (see memory ``volc_podcast_token_refresh``).
- ``VOLC_CLUSTER`` — usually ``volcengine_streaming_common`` or the ASR-specific
  cluster the app has permissions for. Falls back to ``volcengine_streaming_common``.

Protocol (simplified):
1. Connect with ``X-Api-App-Key`` / ``X-Api-Access-Key`` / ``X-Api-Resource-Id``
   headers.
2. Send an initial JSON config frame (audio format, sample rate, language).
3. Stream 16k mono 16-bit PCM chunks as binary frames.
4. Receive JSON frames with ``result.text`` (partial or final).

This module wraps the client in an async generator: caller feeds PCM chunks
via ``send_audio``, iterates ``transcripts()`` for text updates, and closes
via ``close()`` to flush the final result.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import struct
import uuid
from dataclasses import dataclass

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover
    websockets = None  # type: ignore


ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

# Byte protocol constants — see Volc SAUC bigmodel docs. Kept minimal here.
PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010
FULL_SERVER_RESPONSE = 0b1001
NO_SEQUENCE = 0b0000
POS_SEQUENCE = 0b0001
NEG_SEQUENCE = 0b0010
JSON_SERIALIZATION = 0b0001
GZIP_COMPRESSION = 0b0001


@dataclass
class Transcript:
    text: str
    is_final: bool


def _build_header(
    message_type: int, flags: int, serialization: int = JSON_SERIALIZATION
) -> bytes:
    b0 = (PROTOCOL_VERSION << 4) | DEFAULT_HEADER_SIZE
    b1 = (message_type << 4) | flags
    b2 = (serialization << 4) | GZIP_COMPRESSION
    b3 = 0
    return bytes([b0, b1, b2, b3])


class VolcASR:
    def __init__(
        self,
        app_id: str | None = None,
        access_token: str | None = None,
        resource_id: str = "volc.bigasr.sauc.duration",
        sample_rate: int = 16000,
        language: str = "zh-CN",
    ) -> None:
        if websockets is None:
            raise RuntimeError("volc ASR needs `pip install websockets`")
        self.app_id = app_id or os.environ.get("VOLC_APP_ID") or ""
        self.access_token = access_token or os.environ.get("VOLC_ACCESS_TOKEN") or ""
        if not self.app_id or not self.access_token:
            raise RuntimeError(
                "VOLC_APP_ID and VOLC_ACCESS_TOKEN must be set (see memory "
                "'volc_podcast_token_refresh' for how to obtain them)"
            )
        self.resource_id = resource_id
        self.sample_rate = sample_rate
        self.language = language
        self._ws: any = None  # noqa: ANN401
        self._recv_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[Transcript] = asyncio.Queue()
        self._closed = False

    async def start(self) -> None:
        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": uuid.uuid4().hex,
        }
        self._ws = await websockets.connect(ASR_URL, additional_headers=headers)
        # Initial config frame
        config = {
            "app": {"appid": self.app_id, "cluster": os.environ.get("VOLC_CLUSTER", "volcengine_streaming_common")},
            "user": {"uid": "sense-use"},
            "audio": {
                "format": "raw",
                "codec": "raw",
                "rate": self.sample_rate,
                "bits": 16,
                "channel": 1,
                "language": self.language,
            },
            "request": {"reqid": uuid.uuid4().hex, "nbest": 1, "workflow": "audio_in,resample,partition,vad,fe,decode"},
        }
        payload = gzip.compress(json.dumps(config).encode("utf-8"))
        frame = _build_header(FULL_CLIENT_REQUEST, POS_SEQUENCE) + struct.pack(">I", 1) + struct.pack(">I", len(payload)) + payload
        await self._ws.send(frame)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def send_audio(self, pcm_chunk: bytes, seq: int, final: bool = False) -> None:
        if self._ws is None or self._closed:
            return
        payload = gzip.compress(pcm_chunk)
        flags = NEG_SEQUENCE if final else POS_SEQUENCE
        header = _build_header(AUDIO_ONLY_REQUEST, flags, serialization=0)
        signed_seq = -seq if final else seq
        frame = header + struct.pack(">i", signed_seq) + struct.pack(">I", len(payload)) + payload
        await self._ws.send(frame)

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if not isinstance(raw, (bytes, bytearray)) or len(raw) < 4:
                    continue
                header1, header2 = raw[1], raw[2]
                msg_type = header1 >> 4
                if msg_type != FULL_SERVER_RESPONSE:
                    continue
                offset = 4
                # skip optional sequence
                if (header1 & 0x0F) in (POS_SEQUENCE, NEG_SEQUENCE):
                    offset += 4
                payload_len = struct.unpack(">I", raw[offset:offset + 4])[0]
                offset += 4
                payload = raw[offset:offset + payload_len]
                if (header2 & 0x0F) == GZIP_COMPRESSION:
                    payload = gzip.decompress(payload)
                try:
                    obj = json.loads(payload.decode("utf-8"))
                except Exception:
                    continue
                text = ((obj.get("result") or {}).get("text")) or ""
                is_final = bool(obj.get("is_final") or (header1 & 0x0F) == NEG_SEQUENCE)
                if text or is_final:
                    await self._queue.put(Transcript(text=text, is_final=is_final))
        except Exception:  # noqa: BLE001
            pass
        finally:
            await self._queue.put(Transcript(text="", is_final=True))

    async def transcripts(self):
        while True:
            t = await self._queue.get()
            yield t
            if t.is_final:
                return

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._recv_task is not None:
            try:
                await asyncio.wait_for(self._recv_task, timeout=1.0)
            except Exception:
                pass
