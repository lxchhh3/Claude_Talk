"""Talks to the real Open JTalk engine and plays audio. Opt in with
CLAUDE_TALK_AUDIO=1 so the default suite stays silent and fast."""
import os
import time

import numpy as np
import pytest

from claude_talk.jtalk import MEI_VOICE, OpenJTalkBackend
from claude_talk.speaker import CompositeBackend, SapiBackend, Speaker, WindowsMutexLock

pytestmark = pytest.mark.integration

if os.environ.get("CLAUDE_TALK_AUDIO") != "1":
    pytest.skip("set CLAUDE_TALK_AUDIO=1 to run the audio tests", allow_module_level=True)


def test_real_synth_returns_audio_in_int16_scale():
    backend = OpenJTalkBackend()
    x, sr = backend._synth("テストが終わりました。", 1.05, 6.0)
    assert sr == 48000
    assert len(x) / sr > 0.8
    assert 2000 < np.abs(x).max() <= 32767


@pytest.fixture
def speaker():
    s = Speaker(
        lambda: CompositeBackend.from_factories([SapiBackend, OpenJTalkBackend]),
        lock=WindowsMutexLock(),
    )
    yield s
    s.close(timeout=5)


def test_japanese_message_plays_through_mei(speaker):
    assert MEI_VOICE in speaker.voices()
    r = speaker.speak("ゆっくりしていってね。テストが終わりました。", max_chars=200)
    assert r.voice == MEI_VOICE
    assert speaker.wait_speaking(10)
    t0 = time.perf_counter()
    assert speaker.wait_idle(20)
    assert time.perf_counter() - t0 > 1.0, "returned too fast: nothing was played"


def test_english_label_then_japanese_body_uses_both_engines(speaker):
    r = speaker.speak("ビルドが成功しました。", prefix="Claude Talk", prefix_voice="zira", max_chars=200)
    assert r.voice == MEI_VOICE
    assert speaker.wait_idle(20)


def test_stop_cuts_mei_short(speaker):
    speaker.speak("この文章はとても長くて、ずっと続きます。" * 6, max_chars=800)
    assert speaker.wait_speaking(10)
    time.sleep(1.0)
    t0 = time.perf_counter()
    speaker.stop()
    assert speaker.wait_idle(5)
    assert time.perf_counter() - t0 < 1.5, "stop() did not interrupt playback"
