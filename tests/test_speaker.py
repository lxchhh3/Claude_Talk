import threading

import pytest
from conftest import AVAIL, DAVID, YUKKURI, ZIRA, FakeBackend, FakeLock

from claude_talk.speaker import CompositeBackend


def test_backend_factory_runs_on_the_worker_thread(make_speaker):
    seen = {}

    def factory():
        seen["thread"] = threading.current_thread().name
        return FakeBackend()

    assert make_speaker(factory).wait_ready(5)
    assert seen["thread"] != threading.current_thread().name


def test_speak_sends_cleaned_text_and_default_voice(backend, speaker):
    r = speaker.speak("**done**")
    assert speaker.wait_idle(5)
    assert backend.calls == [("done.", ZIRA, 0, 100)]
    assert r.text == "done."
    assert r.voice == ZIRA
    assert r.truncated is False


def test_order_is_preserved(backend, speaker):
    for w in ("a", "b", "c"):
        speaker.speak(w)
    assert speaker.wait_idle(5)
    assert [c[0] for c in backend.calls] == ["a.", "b.", "c."]


def test_rate_and_volume_are_clamped(backend, speaker):
    speaker.speak("fast", rate=50, volume=300)
    speaker.speak("slow", rate=-50, volume=-5)
    assert speaker.wait_idle(5)
    assert backend.calls[0][2:] == (10, 100)
    assert backend.calls[1][2:] == (-10, 0)


def test_voice_override_by_substring(backend, speaker):
    r = speaker.speak("hello", voice="david")
    assert speaker.wait_idle(5)
    assert r.voice == DAVID
    assert backend.calls[0][1] == DAVID


def test_chinese_is_dropped_and_voice_stays_english(backend, speaker):
    r = speaker.speak("测试通过 done")
    assert (r.text, r.voice) == ("done.", ZIRA)
    with pytest.raises(ValueError):
        speaker.speak("测试通过")  # nothing left to say once Chinese is gone


def test_japanese_text_selects_yukkuri(backend, speaker):
    r = speaker.speak("テスト完了")
    assert speaker.wait_idle(5)
    assert (r.text, r.voice) == ("テスト完了。", YUKKURI)
    assert backend.calls[0][1] == YUKKURI


def test_prefix_in_another_voice_is_spoken_first_in_the_same_utterance(backend, speaker):
    r = speaker.speak("テスト完了", prefix="Claude Talk", prefix_voice="zira")
    assert speaker.wait_idle(5)
    assert backend.calls == [("Claude Talk.", ZIRA, 0, 100), ("テスト完了。", YUKKURI, 0, 100)]
    assert (r.text, r.voice) == ("テスト完了。", YUKKURI)


def test_prefix_with_same_voice_is_merged_into_one_call(backend, speaker):
    speaker.speak("tests passed", prefix="Claude Talk", prefix_voice="zira")
    assert speaker.wait_idle(5)
    assert backend.calls == [("Claude Talk. tests passed.", ZIRA, 0, 100)]


def test_prefix_and_body_share_one_lock_acquisition(backend, make_speaker):
    lock = FakeLock()
    s = make_speaker(lambda: backend, lock)
    s.speak("テスト完了", prefix="Claude Talk", prefix_voice="zira")
    assert s.wait_idle(5)
    assert len(backend.calls) == 2
    assert (lock.acquired, lock.released) == (1, 1)


# ------------------------------------------------------------ composite
def test_composite_unions_voices_and_routes_by_name():
    a, b = FakeBackend(voices=["A1", "A2"]), FakeBackend(voices=["B1"])
    c = CompositeBackend([a, b])
    assert c.voices() == ["A1", "A2", "B1"]
    c.speak("x", "B1", 1, 90)
    c.speak("y", "A2", 0, 100)
    assert b.calls == [("x", "B1", 1, 90)]
    assert a.calls == [("y", "A2", 0, 100)]


def test_composite_unknown_voice_raises():
    c = CompositeBackend([FakeBackend(voices=["A1"])])
    with pytest.raises(ValueError):
        c.speak("x", "nope", 0, 100)


def test_composite_stop_and_close_fan_out():
    a, b = FakeBackend(voices=["A1"]), FakeBackend(voices=["B1"])
    c = CompositeBackend([a, b])
    c.stop()
    assert (a.stopped, b.stopped) == (1, 1)
    c.close()
    assert a.closed_in_thread == b.closed_in_thread == threading.current_thread().name


def test_composite_tolerates_a_backend_that_fails_to_start():
    def boom():
        raise RuntimeError("no engine")

    c = CompositeBackend.from_factories([boom, lambda: FakeBackend(voices=["A1"])])
    assert c.voices() == ["A1"]
    assert c.failures and "no engine" in c.failures[0]


def test_long_text_is_truncated_and_reported(backend, speaker):
    r = speaker.speak("First sentence. " * 100, max_chars=40)
    assert speaker.wait_idle(5)
    assert r.truncated is True
    assert len(backend.calls[0][0]) <= 40
    assert backend.calls[0][0].endswith(".")


def test_empty_text_raises(speaker):
    with pytest.raises(ValueError):
        speaker.speak("   ")


def test_voices_lists_backend_voices(speaker):
    assert speaker.voices() == AVAIL


def test_lock_is_taken_once_per_utterance(backend, make_speaker):
    lock = FakeLock()
    s = make_speaker(lambda: backend, lock)
    s.speak("one")
    s.speak("two")
    assert s.wait_idle(5)
    assert (lock.acquired, lock.released) == (2, 2)
    assert lock.held is False


def test_stop_purges_pending_and_interrupts_current(make_speaker):
    backend = FakeBackend(block=True)
    s = make_speaker(lambda: backend)
    s.speak("a")
    s.speak("b")
    s.speak("c")
    # give the worker a moment to pick up "a" and block inside speak()
    assert s.wait_speaking(5)
    assert s.stop() == 2
    assert backend.stopped == 1
    backend.gate.set()
    assert s.wait_idle(5)
    assert [c[0] for c in backend.calls] == ["a."]


def test_interrupt_flag_purges_pending_then_queues_new(make_speaker):
    backend = FakeBackend(block=True)
    s = make_speaker(lambda: backend)
    s.speak("a")
    s.speak("b")
    assert s.wait_speaking(5)
    assert s.speak("c", interrupt=True).purged == 1
    assert backend.stopped == 1
    backend.gate.set()
    assert s.wait_idle(5)
    assert [c[0] for c in backend.calls] == ["a.", "c."]


def test_close_stops_worker(backend, make_speaker):
    s = make_speaker(lambda: backend)
    s.speak("bye")
    assert s.wait_idle(5)
    s.close(timeout=5)
    assert not s.is_alive()


def test_close_releases_backend_on_the_worker_thread(backend, make_speaker):
    # COM objects must be released by the thread that created them, or
    # pywin32 prints "Win32 exception occurred releasing IUnknown" at exit.
    s = make_speaker(lambda: backend)
    assert s.wait_ready(5)
    s.close(timeout=5)
    assert backend.closed_in_thread == "claude-talk-speaker"


def test_close_without_backend_close_method_is_fine(make_speaker):
    class Minimal:
        def voices(self):
            return AVAIL

        def speak(self, *a):
            pass

        def stop(self):
            pass

    s = make_speaker(Minimal)
    s.speak("x")
    assert s.wait_idle(5)
    s.close(timeout=5)
    assert not s.is_alive()
