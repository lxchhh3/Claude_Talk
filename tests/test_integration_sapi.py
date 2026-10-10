"""Talks to the real Windows SAPI engine and plays audio. Opt in with
CLAUDE_TALK_AUDIO=1 so the default suite stays silent and fast."""
import os
import time

import pytest

from claude_talk.speaker import SapiBackend, Speaker, WindowsMutexLock

pytestmark = pytest.mark.integration

if os.environ.get("CLAUDE_TALK_AUDIO") != "1":
    pytest.skip("set CLAUDE_TALK_AUDIO=1 to run the audio tests", allow_module_level=True)


@pytest.fixture
def speaker():
    s = Speaker(SapiBackend, lock=WindowsMutexLock())
    yield s
    s.close(timeout=5)


def test_sapi_lists_the_installed_voices(speaker):
    names = speaker.voices()
    assert any("Zira" in n for n in names), names


def test_short_sentence_takes_real_time_to_say(speaker):
    speaker.speak("Claude Talk audio test.", max_chars=100)
    assert speaker.wait_speaking(5)
    t0 = time.perf_counter()
    assert speaker.wait_idle(10)
    assert time.perf_counter() - t0 > 0.5, "returned too fast: nothing was synthesised"


def test_stop_cuts_a_long_utterance_short(speaker):
    speaker.speak("This sentence goes on and on. " * 20, max_chars=800)
    assert speaker.wait_speaking(5)
    time.sleep(0.7)
    t0 = time.perf_counter()
    speaker.stop()
    assert speaker.wait_idle(5)
    assert time.perf_counter() - t0 < 1.5, "stop() did not interrupt the engine"


def test_chinese_is_dropped_and_the_rest_is_spoken_by_zira(speaker):
    r = speaker.speak("测试完成。 No Chinese please.", max_chars=100)
    assert "Zira" in r.voice
    assert r.text == "No Chinese please."
    assert speaker.wait_idle(10)


def test_japanese_plays_with_haruka(speaker):
    r = speaker.speak("テスト完了しました。", max_chars=100)
    assert "Haruka" in r.voice
    assert speaker.wait_speaking(5)
    t0 = time.perf_counter()
    assert speaker.wait_idle(10)
    assert time.perf_counter() - t0 > 0.5
