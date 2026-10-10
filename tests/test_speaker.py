import threading

import pytest

from claude_talk.speaker import CompositeBackend, Speaker

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
def backend():
    return FakeBackend()


@pytest.fixture
def speaker(backend):
    s = Speaker(lambda: backend, lock=FakeLock())
    yield s
    s.close(timeout=5)


def test_backend_factory_runs_on_the_worker_thread():
    seen = {}

    def factory():
        seen["thread"] = threading.current_thread().name
        return FakeBackend()

    s = Speaker(factory, lock=FakeLock())
    try:
        assert s.wait_ready(5)
        assert seen["thread"] != threading.current_thread().name
    finally:
        s.close(timeout=5)


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
    assert backend.calls == [
        ("Claude Talk.", ZIRA, 0, 100),
        ("テスト完了。", YUKKURI, 0, 100),
    ]
    assert (r.text, r.voice) == ("テスト完了。", YUKKURI)


def test_prefix_with_same_voice_is_merged_into_one_call(backend, speaker):
    speaker.speak("tests passed", prefix="Claude Talk", prefix_voice="zira")
    assert speaker.wait_idle(5)
    assert backend.calls == [("Claude Talk. tests passed.", ZIRA, 0, 100)]


def test_prefix_and_body_share_one_lock_acquisition(backend):
    lock = FakeLock()
    s = Speaker(lambda: backend, lock=lock)
    try:
        s.speak("テスト完了", prefix="Claude Talk", prefix_voice="zira")
        assert s.wait_idle(5)
        assert len(backend.calls) == 2
        assert (lock.acquired, lock.released) == (1, 1)
    finally:
        s.close(timeout=5)


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
    long = "First sentence. " * 100
    r = speaker.speak(long, max_chars=40)
    assert speaker.wait_idle(5)
    assert r.truncated is True
    assert len(backend.calls[0][0]) <= 40
    assert backend.calls[0][0].endswith(".")


def test_empty_text_raises(speaker):
    with pytest.raises(ValueError):
        speaker.speak("   ")


def test_voices_lists_backend_voices(speaker):
    assert speaker.voices() == AVAIL


def test_lock_is_taken_once_per_utterance(backend):
    lock = FakeLock()
    s = Speaker(lambda: backend, lock=lock)
    try:
        s.speak("one")
        s.speak("two")
        assert s.wait_idle(5)
        assert (lock.acquired, lock.released) == (2, 2)
        assert lock.held is False
    finally:
        s.close(timeout=5)


def test_stop_purges_pending_and_interrupts_current():
    backend = FakeBackend(block=True)
    s = Speaker(lambda: backend, lock=FakeLock())
    try:
        s.speak("a")
        s.speak("b")
        s.speak("c")
        # give the worker a moment to pick up "a" and block inside speak()
        assert s.wait_speaking(5)
        purged = s.stop()
        assert purged == 2
        assert backend.stopped == 1
        backend.gate.set()
        assert s.wait_idle(5)
        assert [c[0] for c in backend.calls] == ["a."]
    finally:
        s.close(timeout=5)


def test_interrupt_flag_purges_pending_then_queues_new():
    backend = FakeBackend(block=True)
    s = Speaker(lambda: backend, lock=FakeLock())
    try:
        s.speak("a")
        s.speak("b")
        assert s.wait_speaking(5)
        r = s.speak("c", interrupt=True)
        assert r.purged == 1
        assert backend.stopped == 1
        backend.gate.set()
        assert s.wait_idle(5)
        assert [c[0] for c in backend.calls] == ["a.", "c."]
    finally:
        s.close(timeout=5)


def test_close_stops_worker(backend):
    s = Speaker(lambda: backend, lock=FakeLock())
    s.speak("bye")
    assert s.wait_idle(5)
    s.close(timeout=5)
    assert not s.is_alive()


def test_close_releases_backend_on_the_worker_thread(backend):
    # COM objects must be released by the thread that created them, or
    # pywin32 prints "Win32 exception occurred releasing IUnknown" at exit.
    s = Speaker(lambda: backend, lock=FakeLock())
    assert s.wait_ready(5)
    s.close(timeout=5)
    assert backend.closed_in_thread == "claude-talk-speaker"


def test_close_without_backend_close_method_is_fine():
    class Minimal:
        def voices(self):
            return AVAIL

        def speak(self, *a):
            pass

        def stop(self):
            pass

    s = Speaker(Minimal, lock=FakeLock())
    s.speak("x")
    assert s.wait_idle(5)
    s.close(timeout=5)
    assert not s.is_alive()
