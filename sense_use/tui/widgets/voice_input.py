"""VoiceInput helper — hold-to-talk voice capture that funnels partial ASR
results back into the parent Input widget.

Design notes
------------

Terminal key events don't distinguish hold-vs-tap reliably. So we use a
*toggle* model: press Ctrl+Space to start recording; press it again to stop.
While recording:

- ``sounddevice`` streams 16 kHz mono PCM chunks
- ``VolcASR`` returns partial transcripts
- Each partial is written into the Input widget as *provisional* text
- On stop the final transcript replaces the provisional block

If ``sounddevice`` or ``websockets`` aren't installed, ``VoiceCapture`` raises
on ``.start()`` — the TUI wraps that with a friendly error line.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

try:
    import numpy as np  # type: ignore
    import sounddevice as sd  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore
    sd = None  # type: ignore

from sense_use.voice.volc_asr import VolcASR


@dataclass
class VoiceEvent:
    kind: str  # "partial" / "final" / "error"
    text: str = ""


class VoiceCapture:
    """Owns one ASR session. `events()` yields VoiceEvent until `stop()`."""

    def __init__(self, sample_rate: int = 16000, chunk_ms: int = 100) -> None:
        if sd is None or np is None:
            raise RuntimeError("voice input needs `pip install sounddevice numpy`")
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_ms / 1000)
        self._asr: VolcASR | None = None
        self._events: asyncio.Queue[VoiceEvent] = asyncio.Queue()
        self._stopping = asyncio.Event()
        self._seq = 1
        self._audio_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._asr = VolcASR(sample_rate=self.sample_rate)
        await self._asr.start()
        self._audio_task = asyncio.create_task(self._audio_loop())
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def _audio_loop(self) -> None:
        assert self._asr is not None
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def _cb(indata, frames, time_info, status) -> None:  # noqa: ANN001
            pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
            loop.call_soon_threadsafe(queue.put_nowait, pcm)

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.chunk_samples,
                callback=_cb,
            ):
                while not self._stopping.is_set():
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    await self._asr.send_audio(chunk, seq=self._seq)
                    self._seq += 1
                # send an empty final frame
                await self._asr.send_audio(b"", seq=self._seq, final=True)
        except Exception as e:  # noqa: BLE001
            await self._events.put(VoiceEvent(kind="error", text=str(e)))

    async def _recv_loop(self) -> None:
        assert self._asr is not None
        try:
            async for tr in self._asr.transcripts():
                kind = "final" if tr.is_final else "partial"
                await self._events.put(VoiceEvent(kind=kind, text=tr.text))
                if tr.is_final:
                    break
        except Exception as e:  # noqa: BLE001
            await self._events.put(VoiceEvent(kind="error", text=str(e)))

    async def events(self):
        while True:
            ev = await self._events.get()
            yield ev
            if ev.kind in ("final", "error"):
                return

    async def stop(self) -> None:
        self._stopping.set()
        if self._asr is not None:
            await self._asr.close()
        for t in (self._audio_task, self._recv_task):
            if t is not None:
                try:
                    await asyncio.wait_for(t, timeout=2.0)
                except Exception:  # noqa: BLE001
                    pass
