"""Runs the real AquesTalkPlayer command line and plays audio. Opt in with
CLAUDE_TALK_AUDIO=1; skipped when the player is not under the project root."""
import os
import time

import pytest

from claude_talk.aquestalk import MARISA_VOICE, REIMU_VOICE, AquesTalkPlayerBackend, find_aquestalk_exe
from claude_talk.speaker import CompositeBackend, SapiBackend, Speaker, WindowsMutexLock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.environ.get("CLAUDE_TALK_AQTK_EXE") or find_aquestalk_exe(ROOT)

pytestmark = pytest.mark.integration

if os.environ.get("CLAUDE_TALK_AUDIO") != "1":
    pytest.skip("set CLAUDE_TALK_AUDIO=1 to run the audio tests", allow_module_level=True)
if not EXE:
    pytest.skip("AquesTalkPlayer.exe not found", allow_module_level=True)


@pytest.fixture
def speaker():
    s = Speaker(
        lambda: CompositeBackend.from_factories([SapiBackend, lambda: AquesTalkPlayerBackend(EXE)]),
        lock=WindowsMutexLock(),
    )
    yield s
    s.close(timeout=5)


def test_reimu_is_the_default_japanese_voice_and_plays(speaker):
    assert REIMU_VOICE in speaker.voices() and MARISA_VOICE in speaker.voices()
    r = speaker.speak("ゆっくりしていってね。テストが終わりました。", max_chars=200)
    assert r.voice == REIMU_VOICE
    assert speaker.wait_speaking(10)
    t0 = time.perf_counter()
    assert speaker.wait_idle(20)
    assert time.perf_counter() - t0 > 1.0, "returned too fast: nothing was played"


def test_english_label_then_reimu_body(speaker):
    r = speaker.speak("ビルドが成功しました。", prefix="Claude Talk", prefix_voice="zira", max_chars=200)
    assert r.voice == REIMU_VOICE
    assert speaker.wait_idle(20)


def test_marisa_by_name(speaker):
    r = speaker.speak("まりさだぜ。", voice="marisa", max_chars=200)
    assert r.voice == MARISA_VOICE
    assert speaker.wait_idle(20)


def test_stop_cuts_reimu_short(speaker):
    speaker.speak("この文章はとても長くて、ずっと続きます。" * 6, max_chars=800)
    assert speaker.wait_speaking(10)
    time.sleep(1.0)
    t0 = time.perf_counter()
    speaker.stop()
    assert speaker.wait_idle(5)
    assert time.perf_counter() - t0 < 1.5, "stop() did not interrupt playback"
