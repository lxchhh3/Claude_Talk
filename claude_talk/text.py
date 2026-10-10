"""Turn a chat-style message into something a TTS engine can read aloud.

Pure functions, no Windows dependencies, so the whole module is unit-testable.
"""
from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 800

# Which installed voices to prefer per detected script, in order, matched as
# case-insensitive substrings of a voice name. Japanese goes to the real
# yukkuri voice (AquesTalkPlayer, Reimu), then Open JTalk's Mei, then Windows'
# Haruka, whichever engine is present. There is no Chinese entry on purpose:
# the user does not want to hear Chinese, so clean_text() removes it instead.
DEFAULT_VOICES: dict[str, tuple[str, ...]] = {
    "en": ("Zira",),
    "ja": ("Yukkuri Reimu", "Yukkuri", "Mei", "Haruka"),
}

_CODE_MARK = " (code omitted) "
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"(?:https?|ftp)://\S+")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
# single * or _ emphasis; the look-arounds keep snake_case names intact
_ITALIC = re.compile(r"(?<![\w*_])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*_])")
_STRIKE = re.compile(r"~~(.+?)~~")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_QUOTE = re.compile(r"^\s*>+\s?")
_HRULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_WS = re.compile(r"\s+")

# Script detection. Kana only ever appear in Japanese; Chinese text has none.
_KANA = re.compile(r"[぀-ヿㇰ-ㇿ]")
_IDEOGRAPH = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f]")
# Everything East Asian: radicals, kana, CJK punctuation, ideographs, Hangul,
# compatibility ideographs, fullwidth forms, supplementary ideographic planes.
_CJK_ALL = re.compile(
    r"[⺀-鿿가-힯豈-﫿＀-￯\U00020000-\U0003134f]+"
)
_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]+")

# characters after which a spoken pause already happens
_TERMINAL = ".!?:;,…。！？：；，"
_SENTENCE_END = ".!?。！？"


def detect_language(text: str) -> str:
    """'ja' if any kana, else 'zh' if any CJK ideograph, else 'en'.
    A kana-less run of kanji is indistinguishable from Chinese and counts as such."""
    if _KANA.search(text):
        return "ja"
    if _IDEOGRAPH.search(text):
        return "zh"
    return "en"


def _finish(fragment: str, ja: bool = False) -> str:
    """Give a fragment terminal punctuation so the engine pauses after it."""
    fragment = fragment.rstrip()
    if not fragment:
        return ""
    # look past closing quotes/brackets: `said "done."` is already terminated
    core = fragment.rstrip(")]\"'”’")
    if core and core[-1] in _TERMINAL:
        return fragment
    return fragment + ("。" if ja else ".")


def clean_text(text: str) -> str:
    """Strip markdown and layout so the text reads naturally when spoken.
    Chinese (and Korean, which has no voice here) is removed; Japanese stays."""
    if not text or not text.strip():
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FENCE.sub(_CODE_MARK, text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("link", text)
    text = _BOLD.sub(r"\2", text)
    text = _ITALIC.sub(r"\2", text)
    text = _STRIKE.sub(r"\1", text)
    ja = detect_language(text) == "ja"
    if ja:
        text = _HANGUL.sub(" ", text)
    else:
        text = _CJK_ALL.sub(" ", text)
    text = text.replace("|", " ")

    paragraphs: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        pieces: list[str] = []
        for line in para.split("\n"):
            if _HRULE.match(line):
                continue
            line = _QUOTE.sub("", line)
            structural = False
            if _HEADER.match(line):
                line = _HEADER.sub("", line)
                structural = True
            elif _BULLET.match(line):
                line = _BULLET.sub("", line)
                structural = True
            line = _WS.sub(" ", line).strip()
            if not line:
                continue
            pieces.append(_finish(line, ja) if structural else line)
        joined = _WS.sub(" ", " ".join(pieces)).strip()
        if joined:
            paragraphs.append(_finish(joined, ja))
    return " ".join(paragraphs)


def truncate(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    """Cut `text` to at most `max_chars`, preferring a sentence boundary,
    then a word boundary. Returns (text, was_truncated)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head = text[:max_chars]
    last_end = max(head.rfind(c) for c in _SENTENCE_END)
    if last_end >= max_chars // 3:
        return head[: last_end + 1].rstrip(), True
    space = head.rfind(" ")
    if space > 0:
        return head[:space].rstrip(), True
    return head, True


def _match(available: list[str], needle: str) -> str | None:
    """A voice whose name (the part before ' (') equals `needle` wins; otherwise
    the first voice containing it. Case-insensitive."""
    needle = needle.lower().strip()
    if not needle:
        return None
    for name in available:
        if name.split(" (")[0].strip().lower() == needle:
            return name
    for name in available:
        if needle in name.lower():
            return name
    return None


def pick_voice(
    text: str,
    available: list[str],
    preferred: str | None = None,
    defaults: dict[str, tuple[str, ...]] = DEFAULT_VOICES,
) -> str:
    """Choose an installed voice: the caller's preference if installed, else
    the defaults for the text's script in order, else whatever is first."""
    if not available:
        raise ValueError("no TTS voices are installed")
    if preferred:
        hit = _match(available, preferred)
        if hit:
            return hit
    lang = detect_language(text)
    for candidate in defaults.get(lang, defaults["en"]):
        hit = _match(available, candidate)
        if hit:
            return hit
    return available[0]
