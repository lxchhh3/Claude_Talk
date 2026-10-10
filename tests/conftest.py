"""Fakes and fixtures shared by the test files (imported as `from conftest import ...`)."""
import io
import threading
import time
import wave
from array import array

import pytest

from claude_talk.speaker import Speaker

AVAIL = [
    "Microsoft David Desktop - English (United States)",
    "Microsoft Zira Desktop - English (United States)",
    "Microsoft Haruka Desktop - Japanese",
    "Microsoft Huihui Desktop - Chinese (Simplified)",
    "Mei (Open JTalk)",
    "Yukkuri Reimu (AquesTalkPlayer れいむ)",
    "Yukkuri Marisa (AquesTalkPlayer まりさ)",
]
DAVID, ZIRA, HARUKA, HUIHUI, MEI, YUKKURI, MARISA = AVAIL


@pytest.fixture
def anyio_backend():
    # mcp ships anyio; pin the backend so pytest does not also try trio.
    return "asyncio"


# --------------------------------------------------------------- speaker
class FakeBackend:
    """Records what the worker asks it to say. `gate` lets a test hold an
    utterance in progress so the queue fills up behind it."""

    def __init__(self, voices=AVAIL, block=False):
        self._voices = list(voices)
        self.calls = []
        self.stopped = 0
        self.gate = threading.Event()
        if not block:
            self.gate.set()

    def voices(self):
        return list(self._voices)

    def speak(self, text, voice, rate, volume):
        self.gate.wait(5)
        self.calls.append((text, voice, rate, volume))

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed_in_thread = threading.current_thread().name


class FakeLock:
    def __init__(self):
        self.acquired = 0
        self.released = 0
        self.held = False

    def acquire(self, timeout):
        assert not self.held, "lock re-entered while held"
        self.held = True
        self.acquired += 1
        return True

    def release(self):
        self.held = False
        self.released += 1


@pytest.fixture
def make_speaker():
    """Speaker(factory, lock=FakeLock() unless given); each one is closed at teardown."""
    made = []

    def make(factory, lock=None):
        made.append(Speaker(factory, lock=lock or FakeLock()))
        return made[-1]

    yield make
    for s in made:
        s.close(timeout=5)


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def speaker(make_speaker, backend):
    return make_speaker(lambda: backend)


# ----------------------------------------------------------------- audio
class FakePlayer:
    """Pretends to play for `duration` seconds, honouring the stop event."""

    def __init__(self):
        self.played = []
        self.purged = 0

    def play(self, wav, duration, stop):
        self.played.append((wav, duration))
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if stop.wait(0.01):
                self.purged += 1
                return


def parse_wav(wav_bytes):
    """(channels, sample width, frame rate, samples) of a 16-bit WAV."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), array("h", w.readframes(w.getnframes()))


def stop_mid_playback(backend, voice, player):
    """Speak a long line on a thread and stop() it once playback started.
    Returns the thread (joined for up to 2 s) and its start time."""
    t = threading.Thread(target=backend.speak, args=("long", voice, 0, 100))
    t0 = time.monotonic()
    t.start()
    while not player.played and time.monotonic() - t0 < 2:
        time.sleep(0.01)
    backend.stop()
    t.join(2)
    return t, t0
