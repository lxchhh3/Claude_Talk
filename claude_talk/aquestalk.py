"""The real yukkuri voice through AQUEST's AquesTalkPlayer command line.

AquesTalkPlayer (free for personal, non-commercial use) bundles the licensed
AquesTalk engines and the AqKanji2Koe reader, so it takes kanji text directly:

    AquesTalkPlayer.exe /T "text" /P "preset" /W out.wav

renders a WAV without opening a window. Presets live in AquesTalkPlayer.preset
next to the exe; "れいむ" is AquesTalk1 f1 with flat (棒読み) reading, the
classic ゆっくり霊夢, and "まりさ" is f2.
"""
from __future__ import annotations

import csv
import glob
import logging
import os
import re
import subprocess
import tempfile
import threading
import wave
from typing import Callable

from .audio import Player, WinsoundPlayer, pcm16_from_frames, to_wav
from .notation import to_plain

log = logging.getLogger("claude_talk")

DEFAULT_PRESETS: dict[str, str] = {"れいむ": "Reimu", "まりさ": "Marisa"}


def voice_name(preset: str, label: str) -> str:
    return f"Yukkuri {label} (AquesTalkPlayer {preset})"


REIMU_VOICE = voice_name("れいむ", "Reimu")
MARISA_VOICE = voice_name("まりさ", "Marisa")


def load_presets(exe: str) -> dict[str, tuple[str, str]]:
    """Preset name -> (engine, voice type) from AquesTalkPlayer.preset next to
    the exe (a cp932 CSV with a header row). Empty when the file is missing."""
    path = os.path.join(os.path.dirname(exe), "AquesTalkPlayer.preset")
    try:
        with open(path, encoding="cp932", newline="") as f:
            rows = list(csv.reader(f))
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return {}
    return {row[0]: (row[2], row[3]) for row in rows[1:] if len(row) >= 4 and row[0]}


def voices_for(presets: dict[str, tuple[str, str]]) -> dict[str, str]:
    """Voice name -> preset name, Reimu and Marisa first (the "Yukkuri" default
    must land on Reimu), then every other preset in file order."""
    out = {voice_name(p, label): p for p, label in DEFAULT_PRESETS.items()}
    out.update({f"{name} (AquesTalkPlayer {e} {t})": name for name, (e, t) in presets.items() if name not in DEFAULT_PRESETS})
    return out

# argv -> return code
Runner = Callable[[list[str], float], int]

_WS = re.compile(r"\s+")


def safe_text(text: str) -> str:
    """One line, no double quotes (they break the player's /T parsing), and
    only characters the player's Shift-JIS side can take."""
    text = text.replace('"', "")
    text = text.encode("cp932", errors="ignore").decode("cp932")
    return _WS.sub(" ", text).strip()


def player_lines(text: str) -> list[str]:
    """Split text into the player's lines: each "#>" notation part (notation
    never contains spaces) on its own line, plain text between them joined.
    The player reads each line in its own mode, so a notation label can sit
    next to a Japanese body."""
    lines: list[str] = []
    for tok in text.split():
        if tok.startswith("#>") or not lines or lines[-1].startswith("#>"):
            lines.append(tok)
        else:
            lines[-1] += " " + tok
    return [s for s in map(safe_text, lines) if s]


def find_aquestalk_exe(root: str) -> str | None:
    """First AquesTalkPlayer.exe at or up to two folders below `root`, or None."""
    for pattern in ("AquesTalkPlayer.exe", "*/AquesTalkPlayer.exe", "*/*/AquesTalkPlayer.exe"):
        hits = sorted(glob.glob(os.path.join(root, pattern)))
        if hits:
            return hits[0]
    return None


def _subprocess_runner(args: list[str], timeout: float) -> int:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags)
    return proc.returncode


class AquesTalkPlayerBackend:
    def __init__(
        self,
        exe: str,
        presets: dict[str, str] | None = None,
        runner: Runner | None = None,
        player: Player | None = None,
        timeout: float = 60.0,
    ) -> None:
        if runner is None and not os.path.isfile(exe):
            raise FileNotFoundError(f"AquesTalkPlayer not found: {exe}")
        self._exe = exe
        if presets is not None:
            self._voice_to_preset = {voice_name(p, l): p for p, l in presets.items()}
        else:
            self._voice_to_preset = voices_for(load_presets(exe))
        self._runner = runner if runner is not None else _subprocess_runner
        self._player = player if player is not None else WinsoundPlayer()
        self._timeout = timeout
        self._stop = threading.Event()

    def voices(self) -> list[str]:
        return list(self._voice_to_preset)

    def speak(self, text: str, voice: str, rate: int, volume: int) -> None:
        preset = self._voice_to_preset.get(voice)
        if preset is None:
            raise ValueError(f"not an AquesTalkPlayer voice: {voice!r}")
        self._stop.clear()
        fd, path = tempfile.mkstemp(prefix="claude_talk_aq_", suffix=".wav")
        os.close(fd)
        os.unlink(path)  # the player creates the file itself
        try:
            lines = player_lines(text)
            rc = self._runner([self._exe, "/T", "\r\n".join(lines), "/P", preset, "/W", path], self._timeout)
            if rc != 0 and any(s.startswith("#>") for s in lines):
                log.warning("AquesTalkPlayer rejected the notation (code %s); retrying as plain text", rc)
                plain = [to_plain(s) if s.startswith("#>") else s for s in lines]
                if os.path.exists(path):
                    os.unlink(path)
                rc = self._runner([self._exe, "/T", "\r\n".join(plain), "/P", preset, "/W", path], self._timeout)
            if rc != 0:
                raise RuntimeError(f"AquesTalkPlayer exited with code {rc} (preset {preset!r})")
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                raise RuntimeError("AquesTalkPlayer wrote no audio")
            with wave.open(path, "rb") as w:
                sr = w.getframerate()
                samples = pcm16_from_frames(w.readframes(w.getnframes()))
            if len(samples) == 0:
                raise RuntimeError("AquesTalkPlayer wrote an empty WAV")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        gain = max(0, min(100, int(volume))) / 100.0
        scaled = samples if gain == 1.0 else [v * gain for v in samples]
        # `rate` is not applied: the player takes speed from the preset only.
        self._player.play(to_wav(scaled, sr), len(samples) / float(sr), self._stop)

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        return None
