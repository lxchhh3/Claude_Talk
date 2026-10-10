"""`voice`: pick the Claude Talk voice from the command line.

    voice                     interactive picker (what a double-click on voice.cmd gets)
    voice list [filter]       numbered list of voices (* marks the default)
    voice play [N|name ...]   play a sample in those voices (none = all of them)
    voice set N|name [-q]     make it the default (writes voice.txt) and confirm aloud
    voice show                what the default is and which voice it resolves to
    voice say TEXT... [--voice V] [--plain]   speak text; English gets the English
                              stress on AquesTalk voices (--plain: the old katakana reading)

Restart Claude Code sessions after `set`; the running servers read voice.txt
only at startup.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from typing import TextIO

from .kana import has_latin, transliterate
from .notation import is_aquestalk_voice, to_notation
from .server import ROOT, default_voice_from_env
from .text import match_voice, pick_voice, preset_name

SAMPLE_JA = "オール テスツ パスト。チェック ザ ログ。"
SAMPLE_EN = "All tests passed. Check the log."
CONFIRM_JA = "これからは この声で 話します。"
CONFIRM_EN = "I will use this voice from now on."

_HEADER = (
    "# Default voice for Claude Talk (written by `voice set`). Lines starting with #\n"
    "# are ignored; the first other line is matched as a substring of a voice name.\n"
    "# Run `voice list` / `voice play` to choose; restart Claude Code after changing.\n"
)


def resolve(selection: str, voices: list[str]) -> str:
    """'7' -> the 7th voice; otherwise match_voice() (exact preset name first:
    "AquesTalk10 F1" is also inside "...F1E"). An empty selection is the first voice."""
    s = selection.strip()
    if s.isdigit():
        i = int(s)
        if 1 <= i <= len(voices):
            return voices[i - 1]
        raise ValueError(f"no voice number {i} (1-{len(voices)})")
    hit = match_voice(voices, s) if s else next(iter(voices), None)
    if hit is None:
        raise ValueError(f"no voice matches {s!r}")
    return hit


def is_english(voice: str) -> bool:
    return "english" in voice.lower()


def _in_voice(voice: str, english: str, japanese: str) -> str:
    """The voice's name, then the line: English for an English voice, katakana otherwise."""
    name = preset_name(voice)
    return f"{name}. {english}" if is_english(voice) else f"{transliterate(name)}。{japanese}"


def sample_for(voice: str) -> str:
    return _in_voice(voice, SAMPLE_EN, SAMPLE_JA)


def confirmation_for(voice: str) -> str:
    return _in_voice(voice, CONFIRM_EN, CONFIRM_JA)


def spoken_for(text: str, voice: str, accent: bool = True) -> tuple[str, str]:
    """(what to send, what to show): English becomes accent notation for an
    AquesTalk voice, katakana for other Japanese voices, stays for English ones."""
    if is_english(voice) or not has_latin(text):
        return text, text
    kana = transliterate(text)
    if accent and is_aquestalk_voice(voice):
        notation = to_notation(text)
        if notation:
            return notation, f"{kana}  (accented)"
    return kana, kana


def write_default(root: str, voice: str) -> str:
    path = os.path.join(root, "voice.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_HEADER + preset_name(voice) + "\n")
    return path


def _build_speaker():
    from .aquestalk import AquesTalkPlayerBackend, find_aquestalk_exe
    from .speaker import CompositeBackend, SapiBackend, Speaker, WindowsMutexLock

    exe = os.environ.get("CLAUDE_TALK_AQTK_EXE") or find_aquestalk_exe(ROOT)
    factories = [SapiBackend]
    if exe:
        factories.insert(0, lambda: AquesTalkPlayerBackend(exe))
    else:
        print("AquesTalkPlayer.exe not found under the project; Windows voices only", file=sys.stderr)
    return Speaker(lambda: CompositeBackend.from_factories(factories), lock=WindowsMutexLock())


# ------------------------------------------- shared by the one-shot commands and the picker
def _current(voices: list[str], env: Mapping[str, str], root: str) -> str:
    """What the default resolves to for Japanese text: the yukkuri route."""
    return pick_voice("テスト", voices, preferred=default_voice_from_env(env, root))


def _list(voices: list[str], current: str, out: TextIO, needle: str = "") -> None:
    for i, v in enumerate(voices, 1):
        if needle in v.lower():
            print(f"{'*' if v == current else ' '}{i:2d}. {v}", file=out)


def _play(speaker, voices: list[str], voice: str, out: TextIO) -> None:
    print(f"{voices.index(voice) + 1:2d}. {voice}", file=out, flush=True)
    speaker.speak(sample_for(voice), voice=voice, max_chars=300)
    speaker.wait_idle(60)


def _confirm(speaker, voice: str) -> None:
    speaker.speak(confirmation_for(voice), voice=voice, max_chars=300)
    speaker.wait_idle(60)


def _say(speaker, text: str, voice: str, accent: bool, out: TextIO) -> None:
    send, shown = spoken_for(text, voice, accent=accent)
    print(f"{voice}: {shown}", file=out, flush=True)
    speaker.speak(send, voice=voice, max_chars=800)
    speaker.wait_idle(120)


def _interactive(speaker, voices: list[str], root: str, env: Mapping[str, str], out: TextIO, inp) -> int:
    """Stay open until the user quits: that is what a double-clicked .cmd needs."""

    def relist() -> str:
        current = _current(voices, env, root)
        print("Claude Talk voices (* = current default)", file=out)
        _list(voices, current, out)
        print(
            "number/name = hear it | set N = make it the default | say TEXT = test a line"
            " | plain TEXT = same without English stress | l = list | q = quit",
            file=out,
            flush=True,
        )
        return current

    current = relist()
    while True:
        try:
            line = inp("> ").strip()
        except EOFError:
            print(file=out)
            return 0
        if not line or line in ("l", "list"):
            current = relist()
            continue
        if line in ("q", "quit", "exit"):
            return 0
        try:
            if line.startswith("set "):
                v = resolve(line[4:], voices)
                path = write_default(root, v)
                print(f"default voice -> {preset_name(v)}  (written to {path}); restart Claude Code to hear it there", file=out, flush=True)
                _confirm(speaker, v)
                current = v
            elif line.startswith(("say ", "plain ")):
                cmd, _, text = line.partition(" ")
                _say(speaker, text.strip(), current, cmd == "say", out)
            else:
                _play(speaker, voices, resolve(line, voices), out)
        except ValueError as exc:
            print(f"error: {exc}", file=out, flush=True)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voice", description="Pick the Claude Talk voice.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("interactive", help="interactive picker (default with no arguments)")
    lst = sub.add_parser("list", help="numbered list of voices")
    lst.add_argument("filter", nargs="?", default="")
    play = sub.add_parser("play", help="play a sample in the given voices, or all")
    play.add_argument("selection", nargs="*")
    st = sub.add_parser("set", help="make a voice the default (writes voice.txt)")
    st.add_argument("selection")
    st.add_argument("-q", "--quiet", action="store_true", help="do not confirm aloud")
    sub.add_parser("show", help="show the default and what it resolves to")
    say = sub.add_parser("say", help="speak text in the default (or given) voice")
    say.add_argument("text", nargs="+")
    say.add_argument("--voice", default=None)
    say.add_argument("--plain", action="store_true", help="katakana only, no English stress")
    return p


def main(
    argv: list[str] | None = None,
    speaker=None,
    root: str = ROOT,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    inp=input,
) -> int:
    args = _parser().parse_args(argv)
    env = os.environ if env is None else env
    out = out or sys.stdout
    cmd = args.cmd or "interactive"
    speaker = speaker or _build_speaker()
    try:
        voices = speaker.voices()
        default = default_voice_from_env(env, root)
        current = _current(voices, env, root)

        if cmd == "interactive":
            return _interactive(speaker, voices, root, env, out, inp)

        if cmd == "list":
            _list(voices, current, out, args.filter.lower())
            return 0

        if cmd == "play":
            for v in [resolve(s, voices) for s in args.selection] if args.selection else voices:
                _play(speaker, voices, v, out)
            return 0

        if cmd == "set":
            v = resolve(args.selection, voices)
            path = write_default(root, v)
            print(f"default voice -> {preset_name(v)}  ({v})\nwritten to {path}", file=out)
            if default_voice_from_env(env, root) != preset_name(v) and env.get("CLAUDE_TALK_VOICE"):
                print(f"note: CLAUDE_TALK_VOICE={env['CLAUDE_TALK_VOICE']!r} overrides voice.txt", file=out)
            print("Restart Claude Code sessions to hear it there.", file=out)
            if not args.quiet:
                _confirm(speaker, v)
            return 0

        if cmd == "show":
            source = "CLAUDE_TALK_VOICE" if (env.get("CLAUDE_TALK_VOICE") or "").strip() else "voice.txt"
            print(f"default: {default if default else '(none)'}  [{source}]\nresolves to: {current}", file=out)
            return 0

        if cmd == "say":
            _say(speaker, " ".join(args.text), resolve(args.voice, voices) if args.voice else current, not args.plain, out)
            return 0
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=out)
        return 2
    finally:
        speaker.close(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
