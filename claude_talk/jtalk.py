"""Optional Japanese fallback voice: Open JTalk's HMM voice (Mei) pitched up a
few semitones. Off by default (CLAUDE_TALK_MEI=1 enables it) because it needs
numpy, whose conda build drags in two OpenMP runtimes (see audio.py /
lesson #314) and whose Mei voice kevin found weird next to the real thing.

pyopenjtalk is imported lazily so the unit tests can inject a fake synthesiser
and a fake player and never touch audio.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

from .audio import Player, WinsoundPlayer, to_wav  # noqa: F401 - re-exported for callers/tests

log = logging.getLogger("claude_talk")

MEI_VOICE = "Mei (Open JTalk)"
DEFAULT_HALF_TONE = 6.0  # semitones above Mei's natural pitch
DEFAULT_SPEED = 1.05

# (text, speed, half_tone) -> (samples in int16 scale, sample rate)
Synth = Callable[[str, float, float], tuple[np.ndarray, int]]


def _pyopenjtalk_synth(text: str, speed: float, half_tone: float) -> tuple[np.ndarray, int]:
    import pyopenjtalk

    return pyopenjtalk.tts(text, speed=speed, half_tone=half_tone)


class OpenJTalkBackend:
    def __init__(
        self,
        half_tone: float = DEFAULT_HALF_TONE,
        speed: float = DEFAULT_SPEED,
        synth: Synth | None = None,
        player: Player | None = None,
    ) -> None:
        self._half_tone = float(half_tone)
        self._speed = float(speed)
        if synth is None:
            import pyopenjtalk  # noqa: F401 - fail at construction, not at first use

            synth = _pyopenjtalk_synth
        self._synth = synth
        self._player = player if player is not None else WinsoundPlayer()
        self._stop = threading.Event()

    def voices(self) -> list[str]:
        return [MEI_VOICE]

    def speak(self, text: str, voice: str, rate: int, volume: int) -> None:
        self._stop.clear()
        rate = max(-10, min(10, int(rate)))
        speed = self._speed * (1.0 + 0.05 * rate)  # rate 10 -> 1.5x, -10 -> 0.5x
        x, sr = self._synth(text, speed, self._half_tone)
        x = np.asarray(x, dtype=np.float64)
        if x.size == 0:
            raise RuntimeError(f"Open JTalk synthesised nothing for {text[:40]!r}")
        gain = max(0, min(100, int(volume))) / 100.0
        self._player.play(to_wav(x * gain, sr), x.size / float(sr), self._stop)

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        return None
