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
from .text import pick_voice

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
    """'7' -> the 7th voice; otherwise the first voice containing the text."""
    s = selection.strip()
    if s.isdigit():
        i = int(s)
        if 1 <= i <= len(voices):
            return voices[i - 1]
        raise ValueError(f"no voice number {i} (1-{len(voices)})")
    for v in voices:  # exact preset name first ("AquesTalk10 F1" is also inside "...F1E")
        if preset_name(v).lower() == s.lower():
            return v
    for v in voices:
        if s.lower() in v.lower():
            return v
    raise ValueError(f"no voice matches {s!r}")


def preset_name(voice: str) -> str:
    """The part before ' (': the preset for AquesTalk voices, a safe substring otherwise."""
    return voice.split(" (")[0].strip()


def is_english(voice: str) -> bool:
    return "english" in voice.lower()


def sample_for(voice: str) -> str:
    name = preset_name(voice)
    if is_english(voice):
        return f"{name}. {SAMPLE_EN}"
    return f"{transliterate(name)}。{SAMPLE_JA}"


def confirmation_for(voice: str) -> str:
    name = preset_name(voice)
    if is_english(voice):
        return f"{name}. {CONFIRM_EN}"
    return f"{transliterate(name)}。{CONFIRM_JA}"


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


def _interactive(speaker, voices: list[str], root: str, env: Mapping[str, str], out: TextIO, inp) -> int:
    """Stay open until the user quits: that is what a double-clicked .cmd needs."""

    def relist() -> str:
        default = default_voice_from_env(env, root)
        current = pick_voice("テスト", voices, preferred=default)
        print("Claude Talk voices (* = current default)", file=out)
        for i, v in enumerate(voices, 1):
            print(f"{'*' if v == current else ' '}{i:2d}. {v}", file=out)
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
                speaker.speak(confirmation_for(v), voice=v, max_chars=300)
                speaker.wait_idle(60)
                current = v
            elif line.startswith(("say ", "plain ")):
                cmd, _, text = line.partition(" ")
                send, shown = spoken_for(text.strip(), current, accent=cmd == "say")
                print(f"{current}: {shown}", file=out, flush=True)
                speaker.speak(send, voice=current, max_chars=800)
                speaker.wait_idle(120)
            else:
                v = resolve(line, voices)
                print(f"{voices.index(v) + 1:2d}. {v}", file=out, flush=True)
                speaker.speak(sample_for(v), voice=v, max_chars=300)
                speaker.wait_idle(60)
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
        current = pick_voice("テスト", voices, preferred=default)  # Japanese text: the yukkuri route

        if cmd == "interactive":
            return _interactive(speaker, voices, root, env, out, inp)

        if cmd == "list":
            needle = getattr(args, "filter", "").lower()
            for i, v in enumerate(voices, 1):
                if needle in v.lower():
                    mark = "*" if v == current else " "
                    print(f"{mark}{i:2d}. {v}", file=out)
            return 0

        if cmd == "play":
            chosen = [resolve(s, voices) for s in args.selection] if args.selection else list(voices)
            for v in chosen:
                print(f"{voices.index(v) + 1:2d}. {v}", file=out, flush=True)
                speaker.speak(sample_for(v), voice=v, max_chars=300)
                speaker.wait_idle(60)
            return 0

        if cmd == "set":
            v = resolve(args.selection, voices)
            path = write_default(root, v)
            print(f"default voice -> {preset_name(v)}  ({v})\nwritten to {path}", file=out)
            if default_voice_from_env(env, root) != preset_name(v) and env.get("CLAUDE_TALK_VOICE"):
                print(f"note: CLAUDE_TALK_VOICE={env['CLAUDE_TALK_VOICE']!r} overrides voice.txt", file=out)
            print("Restart Claude Code sessions to hear it there.", file=out)
            if not args.quiet:
                speaker.speak(confirmation_for(v), voice=v, max_chars=300)
                speaker.wait_idle(60)
            return 0

        if cmd == "show":
            source = "CLAUDE_TALK_VOICE" if (env.get("CLAUDE_TALK_VOICE") or "").strip() else "voice.txt"
            shown = default if default else "(none)"
            print(f"default: {shown}  [{source}]\nresolves to: {current}", file=out)
            return 0

        if cmd == "say":
            text = " ".join(args.text)
            v = resolve(args.voice, voices) if args.voice else current
            send, shown = spoken_for(text, v, accent=not args.plain)
            print(f"{v}: {shown}", file=out)
            speaker.speak(send, voice=v, max_chars=800)
            speaker.wait_idle(120)
            return 0
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=out)
        return 2
    finally:
        speaker.close(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
