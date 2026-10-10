"""OpenJTalkBackend with a fake synthesiser and a fake player: no audio, no
pyopenjtalk import needed."""
import io
import threading
import time
import wave

import numpy as np
import pytest

from claude_talk.jtalk import MEI_VOICE, OpenJTalkBackend, to_wav


class FakeSynth:
    def __init__(self, sr=48000, seconds=0.5, level=1000.0):
        self.calls = []
        self.sr = sr
        self.seconds = seconds
        self.level = level

    def __call__(self, text, speed, half_tone):
        self.calls.append((text, speed, half_tone))
        return np.full(int(self.sr * self.seconds), self.level), self.sr


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


def _parse(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return (
            w.getnchannels(),
            w.getsampwidth(),
            w.getframerate(),
            np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"),
        )


@pytest.fixture
def parts():
    synth, player = FakeSynth(), FakePlayer()
    backend = OpenJTalkBackend(half_tone=6.0, speed=1.05, synth=synth, player=player)
    return synth, player, backend


def test_voice_name_is_mei(parts):
    _, _, backend = parts
    assert backend.voices() == [MEI_VOICE]
    assert "mei" in MEI_VOICE.lower()


def test_speak_synthesises_with_defaults_and_plays_16bit_mono(parts):
    synth, player, backend = parts
    backend.speak("テスト完了。", MEI_VOICE, 0, 100)
    assert synth.calls == [("テスト完了。", 1.05, 6.0)]
    assert len(player.played) == 1
    wav, duration = player.played[0]
    ch, width, sr, samples = _parse(wav)
    assert (ch, width, sr) == (1, 2, 48000)
    assert len(samples) == 24000
    assert duration == pytest.approx(0.5, abs=0.01)
    assert samples[0] == 1000


def test_rate_scales_speed_around_the_base(parts):
    synth, _, backend = parts
    backend.speak("a", MEI_VOICE, 10, 100)
    backend.speak("b", MEI_VOICE, -10, 100)
    backend.speak("c", MEI_VOICE, 0, 100)
    speeds = [c[1] for c in synth.calls]
    assert speeds[0] == pytest.approx(1.05 * 1.5)
    assert speeds[1] == pytest.approx(1.05 * 0.5)
    assert speeds[2] == pytest.approx(1.05)


def test_volume_scales_samples(parts):
    _, player, backend = parts
    backend.speak("x", MEI_VOICE, 0, 50)
    _, _, _, samples = _parse(player.played[0][0])
    assert samples[0] == 500


def test_stop_cuts_playback_short():
    synth, player = FakeSynth(seconds=5.0), FakePlayer()
    backend = OpenJTalkBackend(synth=synth, player=player)
    t = threading.Thread(target=backend.speak, args=("long", MEI_VOICE, 0, 100))
    t0 = time.monotonic()
    t.start()
    while not player.played and time.monotonic() - t0 < 2:
        time.sleep(0.01)
    backend.stop()
    t.join(2)
    assert not t.is_alive(), "speak() did not return after stop()"
    assert player.purged == 1
    assert time.monotonic() - t0 < 2


def test_empty_synthesis_raises():
    def nothing(text, speed, half_tone):
        return np.zeros(0), 48000

    backend = OpenJTalkBackend(synth=nothing, player=FakePlayer())
    with pytest.raises(RuntimeError):
        backend.speak("x", MEI_VOICE, 0, 100)


def test_to_wav_clips_to_int16():
    ch, width, sr, samples = _parse(to_wav(np.array([40000.0, -40000.0, 12.7]), 16000))
    assert (ch, width, sr) == (1, 2, 16000)
    assert list(samples) == [32767, -32768, 13]
