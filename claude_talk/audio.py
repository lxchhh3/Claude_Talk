"""WAV helpers and the winsound player, deliberately numpy-free.

The server process must not import numpy: conda's MKL build of numpy loads
both OpenMP runtimes (an old libiomp5md.dll and LLVM's libomp.dll), which
breaks any wheel carrying its own libiomp5md.dll in the same process (lesson #314).
Only the optional Open JTalk engine needs numpy, and it is off by default.
"""
from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import threading
import time
import wave
from array import array
from typing import Iterable, Protocol

log = logging.getLogger("claude_talk")


class Player(Protocol):
    def play(self, wav: bytes, duration: float, stop: threading.Event) -> None: ...


def pcm16_from_frames(frames: bytes) -> array:
    """Little-endian 16-bit mono frames -> array of ints."""
    arr = array("h", frames)
    if sys.byteorder != "little":
        arr.byteswap()
    return arr


def to_wav(samples: Iterable[float], sr: int) -> bytes:
    """16-bit mono PCM WAV bytes from samples already in int16 scale.
    Values are rounded and clipped. Accepts any iterable of numbers, including
    a numpy array (handled without importing numpy here)."""
    if hasattr(samples, "astype"):  # numpy array: use its own fast path
        import numpy as np

        pcm = np.clip(np.rint(np.asarray(samples, dtype=np.float64)), -32768, 32767).astype("<i2")
        payload = pcm.tobytes()
    else:
        arr = array("h", (max(-32768, min(32767, int(round(v)))) for v in samples))
        if sys.byteorder != "little":
            arr.byteswap()
        payload = arr.tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(payload)
    return buf.getvalue()


class WinsoundPlayer:
    """Plays a WAV through winsound. winsound cannot play from memory
    asynchronously, so the bytes go to a temp file that is removed afterwards;
    the async start is what lets a stop request cut playback short."""

    def __init__(self) -> None:
        self._leftover: str | None = None

    def _cleanup(self, path: str | None) -> None:
        if path:
            try:
                os.unlink(path)
            except OSError:
                self._leftover = path  # still open; retried on the next play
                return
        if self._leftover and self._leftover != path:
            try:
                os.unlink(self._leftover)
                self._leftover = None
            except OSError:
                pass

    def play(self, wav: bytes, duration: float, stop: threading.Event) -> None:
        import winsound

        fd, path = tempfile.mkstemp(prefix="claude_talk_", suffix=".wav")
        with os.fdopen(fd, "wb") as f:
            f.write(wav)
        try:
            winsound.PlaySound(
                path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
            deadline = time.monotonic() + duration + 0.2
            while time.monotonic() < deadline:
                if stop.wait(0.05):
                    winsound.PlaySound(None, 0)  # stops whatever this process is playing
                    break
        finally:
            self._cleanup(path)
