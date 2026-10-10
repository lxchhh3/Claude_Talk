"""MCP server exposing `speak`, `stop_speaking` and `list_voices` over stdio."""
from __future__ import annotations

import contextlib
import importlib
import logging
import os
import sys
import threading
from collections.abc import Callable, Mapping
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from .kana import has_latin
from .notation import is_aquestalk_voice
from .speaker import Speaker
from .text import DEFAULT_MAX_CHARS, clean_text, pick_voice

log = logging.getLogger("claude_talk")

INSTRUCTIONS = (
    "Speaks short messages aloud on the user's PC in a yukkuri (ゆっくり) voice. "
    "The user often has many terminals open or is away from the screen, so call "
    "`speak` when a task finishes, when you are blocked waiting for their input, or "
    "when something needs their attention. English is read in katakana with a "
    "Japanese accent, so plain English or Japanese both work; one or two short "
    "sentences."
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def quiet_import(name: str) -> ModuleType | None:
    """Import an engine module with stdout redirected to stderr.

    stdout is the MCP protocol channel; pyopenjtalk-plus prints an ONNX
    warning to stdout on import, which would corrupt the JSON-RPC stream.
    Call this in main() before the server starts so the later import on the
    worker thread is a cache hit. Returns None if the module is missing."""
    with contextlib.redirect_stdout(sys.stderr):
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            log.warning("engine module %s unavailable: %s", name, exc)
            return None


def preload_runtime(mei: bool) -> None:
    """Load noisy native runtimes before the stdio transport owns stdout."""
    if mei:
        quiet_import("pyopenjtalk")


def project_label_from_env(env: Mapping[str, str], cwd: str) -> str | None:
    """What to say before each message so the user knows which terminal is
    talking. CLAUDE_TALK_PROJECT overrides; 'off' disables; default is the
    working directory's folder name with separators turned into spaces."""
    override = env.get("CLAUDE_TALK_PROJECT")
    if override is not None:
        override = override.strip()
        if override.lower() in ("", "off", "none", "0"):
            return None
        return override
    base = os.path.basename(os.path.normpath(cwd))
    label = base.replace("_", " ").replace("-", " ").strip()
    return label or None


def default_voice_from_env(env: Mapping[str, str], root: str) -> str | None:
    """The voice used when a call names none: CLAUDE_TALK_VOICE, else the first
    non-comment line of <root>/voice.txt, else None (= Reimu for Japanese)."""
    value = (env.get("CLAUDE_TALK_VOICE") or "").strip()
    if value:
        return value
    try:
        with open(os.path.join(root, "voice.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return None


def build_server(
    speaker: Speaker,
    project_label: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    label_voice: str | None = None,
    kana: Callable[[str], str] | None = None,
    default_voice: str | None = None,
    notation: Callable[[str], str | None] | None = None,
) -> FastMCP:
    """`kana` turns Latin-letter runs into katakana (claude_talk.kana.transliterate);
    None leaves English to the Windows English voice. `notation` turns English
    into accent-marked AquesTalk notation (claude_talk.notation.to_notation),
    used instead of the katakana when the text goes to an AquesTalkPlayer
    voice. `default_voice` is the substring used when a call names no voice
    (and for the label unless `label_voice` says otherwise)."""
    mcp = FastMCP("claude-talk", instructions=INSTRUCTIONS)

    def _route(text: str, voice: str | None) -> str | None:
        try:
            return pick_voice(text, speaker.voices(), preferred=voice)
        except Exception:  # noqa: BLE001 - voice list unavailable: let speak() report it
            return None

    def _english_voice_requested(body: str, voice: str | None) -> bool:
        return voice is not None and "english" in (_route(body, voice) or "").lower()

    def _for_engine(english: str, katakana_text: str, voice: str | None) -> str:
        """Notation when the katakana would land on an AquesTalkPlayer voice."""
        if notation is not None and is_aquestalk_voice(_route(katakana_text, voice)):
            return notation(english) or katakana_text
        return katakana_text

    @mcp.tool()
    def speak(
        text: str,
        voice: str | None = None,
        rate: int = 0,
        interrupt: bool = False,
        announce_project: bool = True,
        katakana: bool = True,
    ) -> str:
        """Read a short message aloud on the user's speakers in a yukkuri voice.

        Use it when a task is done, when you are blocked on the user's input, or
        when something needs their attention; they may not be looking at this
        terminal. Keep `text` to one or two short sentences.

        The voice is the classic ゆっくり霊夢 (AquesTalkPlayer). English words are
        transliterated to katakana and read with a Japanese accent ("All tests
        passed" -> オール テスツ パスト), so write plain English or Japanese; the
        reply shows what was actually spoken. Chinese is stripped (the user does
        not want to hear Chinese). Markdown, code blocks and URLs are removed
        before speaking. `voice` is a substring of an installed voice name (see
        list_voices), e.g. "marisa", "zira"; an English voice skips the katakana
        step, as does `katakana=False`. `rate` is -10 (slow) to 10 (fast) for
        the Windows voices only. `interrupt` cuts off anything still being
        spoken. `announce_project` says the project folder name first so the
        user knows which session spoke.
        """
        body = clean_text(text)
        if not body:
            raise ValueError("text is empty")
        wanted = voice or default_voice
        prefix = project_label if announce_project else None
        prefix_voice = label_voice or wanted
        note = ""
        send = body
        if katakana and kana is not None and not _english_voice_requested(body, wanted):
            if has_latin(body):
                spoken = kana(body)
                if spoken != body:
                    note = f' (from "{body}")'
                send = _for_engine(body, spoken, wanted)
                body = spoken
            if prefix and has_latin(prefix):
                prefix = _for_engine(prefix, kana(prefix), prefix_voice)
        result = speaker.speak(
            send,
            voice=wanted,
            rate=rate,
            interrupt=interrupt,
            max_chars=max_chars,
            prefix=prefix,
            prefix_voice=prefix_voice,
        )
        shown = body if send.startswith("#>") else result.text  # never show the raw notation
        msg = f'Queued for {result.voice}: "{shown}"' + note
        if result.truncated:
            msg += f" (truncated to {max_chars} chars)"
        if result.purged:
            msg += f"; cut off {result.purged} pending message(s)"
        return msg

    @mcp.tool()
    def stop_speaking() -> str:
        """Stop talking: cuts off the current utterance and drops anything queued."""
        purged = speaker.stop()
        return f"Stopped; {purged} pending message(s) dropped."

    @mcp.tool()
    def list_voices() -> list[str]:
        """List the voices available to `speak`: the yukkuri presets (Reimu, Marisa) and the Windows SAPI voices."""
        return speaker.voices()

    return mcp


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=os.environ.get("CLAUDE_TALK_LOG", "INFO"),
        format="%(asctime)s claude-talk %(levelname)s %(message)s",
    )
    # the mcp library logs every request at INFO; keep stderr for our own lines
    logging.getLogger("mcp").setLevel(logging.WARNING)
    label = project_label_from_env(os.environ, os.getcwd())
    max_chars = int(os.environ.get("CLAUDE_TALK_MAX_CHARS", DEFAULT_MAX_CHARS))
    label_voice = os.environ.get("CLAUDE_TALK_LABEL_VOICE") or None
    default_voice = default_voice_from_env(os.environ, ROOT)
    mei_on = os.environ.get("CLAUDE_TALK_MEI", "0") == "1"
    preload_runtime(mei=mei_on)

    from .aquestalk import AquesTalkPlayerBackend, find_aquestalk_exe
    from .speaker import CompositeBackend, SapiBackend, WindowsMutexLock

    kana_fn: Callable[[str], str] | None = None
    notation_fn: Callable[[str], str | None] | None = None
    if os.environ.get("CLAUDE_TALK_KATAKANA", "1") != "0":
        from .kana import transliterate, warm

        kana_fn = transliterate
        threading.Thread(target=warm, name="claude-talk-kana-warm", daemon=True).start()
        if os.environ.get("CLAUDE_TALK_ACCENT", "1") != "0":
            from .notation import to_notation

            notation_fn = to_notation

    aq_exe = os.environ.get("CLAUDE_TALK_AQTK_EXE") or find_aquestalk_exe(ROOT)

    def reimu() -> AquesTalkPlayerBackend:
        if not aq_exe:
            raise FileNotFoundError(f"AquesTalkPlayer.exe not found under {ROOT}")
        return AquesTalkPlayerBackend(aq_exe)

    # order matters: the first engine owning "Yukkuri Reimu" wins the default
    factories = [SapiBackend, reimu]
    if mei_on:
        from .jtalk import DEFAULT_HALF_TONE, DEFAULT_SPEED, OpenJTalkBackend

        half_tone = float(os.environ.get("CLAUDE_TALK_PITCH", DEFAULT_HALF_TONE))
        speed = float(os.environ.get("CLAUDE_TALK_SPEED", DEFAULT_SPEED))

        def mei() -> OpenJTalkBackend:
            return OpenJTalkBackend(half_tone=half_tone, speed=speed)

        factories.append(mei)

    def engines() -> CompositeBackend:
        c = CompositeBackend.from_factories(factories)
        for f in c.failures:
            log.warning("engine unavailable: %s", f)
        return c

    speaker = Speaker(engines, lock=WindowsMutexLock())
    server = build_server(
        speaker,
        project_label=label,
        max_chars=max_chars,
        label_voice=label_voice,
        kana=kana_fn,
        default_voice=default_voice,
        notation=notation_fn,
    )
    log.info(
        "starting; cwd=%s label=%r voice=%r max_chars=%d aquestalk=%s katakana=%s accent=%s mei=%s",
        os.getcwd(), label, default_voice, max_chars, aq_exe, kana_fn is not None,
        notation_fn is not None, mei_on,
    )
    try:
        server.run(transport="stdio")
    finally:
        speaker.close(timeout=5)


if __name__ == "__main__":
    main()
