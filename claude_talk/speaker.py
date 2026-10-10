"""A single worker thread that owns the speech engines and plays a queue of
utterances in order. All engine calls happen on that thread, which is what
SAPI's COM object needs; the public methods are safe to call from anywhere.
"""
from __future__ import annotations

import collections
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from .text import DEFAULT_MAX_CHARS, clean_text, pick_voice, truncate

log = logging.getLogger("claude_talk")


class Backend(Protocol):
    def voices(self) -> list[str]: ...

    def speak(self, text: str, voice: str, rate: int, volume: int) -> None: ...

    def stop(self) -> None: ...


class SpeechLock(Protocol):
    """Serialises utterances across processes so two Claude sessions that
    finish at the same moment do not talk over each other."""

    def acquire(self, timeout: float) -> bool: ...

    def release(self) -> None: ...


class NullLock:
    def acquire(self, timeout: float) -> bool:
        return True

    def release(self) -> None:
        return None


@dataclass(frozen=True)
class SpeakResult:
    text: str
    voice: str
    truncated: bool
    purged: int = 0


@dataclass
class _Part:
    text: str
    voice: str
    rate: int
    volume: int


@dataclass
class _Utterance:
    parts: list[_Part] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(p.text for p in self.parts)


def _merge(parts: list[_Part]) -> list[_Part]:
    """Join adjacent parts that share voice/rate/volume into one engine call,
    so an English label and an English body are spoken as one sentence."""
    merged: list[_Part] = []
    for p in parts:
        if merged and (merged[-1].voice, merged[-1].rate, merged[-1].volume) == (
            p.voice,
            p.rate,
            p.volume,
        ):
            merged[-1].text = f"{merged[-1].text} {p.text}"
        else:
            merged.append(_Part(p.text, p.voice, p.rate, p.volume))
    return merged


class CompositeBackend:
    """Several engines behind one Backend face: each voice name is routed to
    the engine that owns it; stop/close fan out to all of them."""

    def __init__(self, backends: Iterable[Backend]) -> None:
        self._backends = list(backends)
        self._route: dict[str, Backend] = {}
        for b in self._backends:
            for v in b.voices():
                self._route.setdefault(v, b)
        self.failures: list[str] = []

    @classmethod
    def from_factories(cls, factories: Iterable[Callable[[], Backend]]) -> "CompositeBackend":
        backends: list[Backend] = []
        failures: list[str] = []
        for f in factories:
            try:
                backends.append(f())
            except Exception as exc:  # noqa: BLE001 - one missing engine must not sink the rest
                name = getattr(f, "__name__", repr(f))
                failures.append(f"{name}: {exc!r}")
                log.exception("speech engine %s failed to start", name)
        c = cls(backends)
        c.failures = failures
        return c

    def voices(self) -> list[str]:
        return [v for b in self._backends for v in b.voices()]

    def speak(self, text: str, voice: str, rate: int, volume: int) -> None:
        b = self._route.get(voice)
        if b is None:
            raise ValueError(f"unknown voice {voice!r}")
        b.speak(text, voice, rate, volume)

    def stop(self) -> None:
        for b in self._backends:
            b.stop()

    def close(self) -> None:
        for b in self._backends:
            close = getattr(b, "close", None)
            if close is not None:
                close()


class Speaker:
    def __init__(
        self,
        backend_factory: Callable[[], Backend],
        lock: SpeechLock | None = None,
        lock_timeout: float = 120.0,
        name: str = "claude-talk-speaker",
    ) -> None:
        self._factory = backend_factory
        self._lock: SpeechLock = lock if lock is not None else NullLock()
        self._lock_timeout = lock_timeout
        self._backend: Backend | None = None
        self._voices: list[str] = []
        self._init_error: BaseException | None = None
        self._ready = threading.Event()
        self._cond = threading.Condition()
        self._queue: collections.deque[_Utterance] = collections.deque()
        self._speaking = False
        self._abort = False
        self._closing = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ worker
    def _run(self) -> None:
        try:
            self._backend = self._factory()
            self._voices = list(self._backend.voices())
            log.info("speech backend ready; voices: %s", ", ".join(self._voices))
        except BaseException as exc:  # noqa: BLE001 - surfaced via speak()
            self._init_error = exc
            log.exception("speech backend failed to start")
        finally:
            self._ready.set()

        try:
            while True:
                with self._cond:
                    while not self._queue and not self._closing:
                        self._cond.wait()
                    if self._closing:
                        return
                    utt = self._queue.popleft()
                    self._speaking = True
                    self._abort = False
                    self._cond.notify_all()
                try:
                    self._say(utt)
                except Exception:  # noqa: BLE001 - one bad utterance must not kill the worker
                    log.exception("utterance failed: %r", utt.text[:80])
                finally:
                    with self._cond:
                        self._speaking = False
                        self._cond.notify_all()
        finally:
            # release the engines on the thread that created them (COM apartment rule)
            close = getattr(self._backend, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:  # noqa: BLE001
                    log.exception("backend close failed")

    def _say(self, utt: _Utterance) -> None:
        assert self._backend is not None
        got = self._lock.acquire(self._lock_timeout)
        if not got:
            log.warning("speech lock busy for %.0fs; speaking anyway", self._lock_timeout)
        try:
            for part in utt.parts:
                if self._abort:
                    break
                self._backend.speak(part.text, part.voice, part.rate, part.volume)
        finally:
            if got:
                self._lock.release()

    # ------------------------------------------------------------ public
    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def voices(self) -> list[str]:
        self._require_backend()
        return list(self._voices)

    def _require_backend(self) -> None:
        if not self._ready.wait(10):
            raise RuntimeError("speech backend did not start within 10 s")
        if self._init_error is not None:
            raise RuntimeError(f"speech backend failed: {self._init_error!r}")

    def speak(
        self,
        text: str,
        voice: str | None = None,
        rate: int = 0,
        volume: int = 100,
        interrupt: bool = False,
        max_chars: int = DEFAULT_MAX_CHARS,
        prefix: str | None = None,
        prefix_voice: str | None = None,
    ) -> SpeakResult:
        """Queue `text`. `prefix` (e.g. the project name) is spoken first in
        `prefix_voice`, as part of the same utterance."""
        cleaned = clean_text(text)
        if not cleaned:
            raise ValueError("nothing to say: text is empty after cleaning")
        cleaned, truncated = truncate(cleaned, max_chars)
        self._require_backend()
        chosen = pick_voice(cleaned, self._voices, preferred=voice)
        rate = max(-10, min(10, int(rate)))
        volume = max(0, min(100, int(volume)))
        parts: list[_Part] = []
        if prefix:
            label = clean_text(prefix)
            if label:
                label_voice = pick_voice(label, self._voices, preferred=prefix_voice)
                parts.append(_Part(label, label_voice, rate, volume))
        parts.append(_Part(cleaned, chosen, rate, volume))
        utt = _Utterance(_merge(parts))
        purged = self.stop() if interrupt else 0
        with self._cond:
            self._queue.append(utt)
            self._cond.notify_all()
        return SpeakResult(cleaned, chosen, truncated, purged)

    def stop(self) -> int:
        """Drop everything pending and cut the current utterance short.
        Returns how many pending utterances were dropped."""
        with self._cond:
            purged = len(self._queue)
            self._queue.clear()
            speaking = self._speaking
            if speaking:
                self._abort = True
        if speaking and self._backend is not None:
            self._backend.stop()
        return purged

    def wait_speaking(self, timeout: float) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: self._speaking, timeout)

    def wait_idle(self, timeout: float) -> bool:
        with self._cond:
            return self._cond.wait_for(
                lambda: not self._queue and not self._speaking, timeout
            )

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def close(self, timeout: float = 5.0) -> None:
        self.stop()
        with self._cond:
            self._closing = True
            self._cond.notify_all()
        self._thread.join(timeout)


# ---------------------------------------------------------------- Windows
class SapiBackend:
    """Windows built-in TTS through the SAPI 5 COM object. Construct it on
    the thread that will call speak(); Speaker does exactly that."""

    _ASYNC = 1  # SVSFlagsAsync
    _PURGE = 2  # SVSFPurgeBeforeSpeak
    _NOT_XML = 16  # SVSFIsNotXML - never let "<" in a message be parsed as SSML

    def __init__(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        self._voice = win32com.client.Dispatch("SAPI.SpVoice")
        tokens = self._voice.GetVoices()
        self._tokens = {}
        for i in range(tokens.Count):
            tok = tokens.Item(i)
            self._tokens[tok.GetDescription()] = tok
        self._stop = threading.Event()

    def voices(self) -> list[str]:
        return list(self._tokens)

    def speak(self, text: str, voice: str, rate: int, volume: int) -> None:
        self._stop.clear()
        tok = self._tokens.get(voice)
        if tok is not None:
            self._voice.Voice = tok
        self._voice.Rate = rate
        self._voice.Volume = volume
        self._voice.Speak(text, self._ASYNC | self._PURGE | self._NOT_XML)
        while not self._voice.WaitUntilDone(100):
            if self._stop.is_set():
                self._voice.Speak("", self._ASYNC | self._PURGE)
                break

    def stop(self) -> None:
        # Only sets a flag: the COM object must be touched from its own thread.
        self._stop.set()

    def close(self) -> None:
        """Drop the COM references and leave the apartment, on this thread."""
        import pythoncom

        self._tokens.clear()
        self._voice = None
        pythoncom.CoUninitialize()


class WindowsMutexLock:
    """Named mutex in the per-session `Local\\` namespace: every Claude Code
    terminal in the same desktop session shares it, so utterances from
    different sessions queue instead of overlapping."""

    def __init__(self, name: str = "Local\\ClaudeTalkSpeak") -> None:
        import win32event

        self._win32event = win32event
        self._handle = win32event.CreateMutex(None, False, name)

    def acquire(self, timeout: float) -> bool:
        rc = self._win32event.WaitForSingleObject(self._handle, int(timeout * 1000))
        return rc in (self._win32event.WAIT_OBJECT_0, self._win32event.WAIT_ABANDONED)

    def release(self) -> None:
        self._win32event.ReleaseMutex(self._handle)
