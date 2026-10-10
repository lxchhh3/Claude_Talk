"""English text -> AquesTalk phonetic notation, so the stress falls where
English puts it instead of where the Japanese reader guesses.

    "Check the log." -> "#>ちぇ'っく/ざろ'ぐ。"

AquesTalkPlayer reads a line starting with "#>" as notation (AQUEST's
音声記号列仕様書 v2.0): hiragana syllables, ' after the accent-nucleus mora
(where the pitch falls), / between accent phrases, 、 。 ？ as pauses. Each
English content word becomes one accent phrase, accented on its primary
stress (claude_talk.kana.word_reading); unstressed function words lean on the
neighbouring content word ("the log" -> ざろ'ぐ). Only text with no Japanese
in it is converted; anything else stays on the normal text path. Only
syllables that AquesTalk1, AquesTalk2 and AquesTalk10 all accept are emitted
(probed against the player: くぁ/ぐぁ/ふゅ/ぢ/づ/ゔ are rejected by some).
"""
from __future__ import annotations

import re

from .kana import Reading, split_word, word_reading

FUNCTION_WORDS = frozenset(
    "a an the of to in on at by for from with into and or but nor as if than is are was were be "
    "been am it its i you he she we they me him us them my your his her our their will would can "
    "could shall should may might must".split()
)

_JAPANESE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
_TOKEN = re.compile(
    r"(?P<word>[A-Za-z]+(?:'[A-Za-z]+)*)"
    r"|(?P<num>\d+(?:[.,]\d+)*)"
    r"|(?P<end>[.!?]+)(?=\s|$)"
    r"|(?P<pause>[,;:])(?=\s|$)"
    r"|(?P<sym>[%&+@])"
)
_SYMBOL_WORDS = {"%": "percent", "&": "and", "+": "plus", "@": "at"}

# ------------------------------------------------------------- numbers
_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand"))


def _below_thousand(n: int) -> list[str]:
    words: list[str] = []
    if n >= 100:
        words += [_ONES[n // 100], "hundred"]
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10])
        n %= 10
    if n:
        words.append(_ONES[n])
    return words


def number_words(token: str) -> list[str]:
    """'159' -> one hundred fifty nine; '3.25' -> three point two five; more
    than 15 digits are read one by one."""
    t = token.replace(",", "")
    if "." in t:
        whole, frac = t.split(".", 1)
        return number_words(whole or "0") + ["point"] + [_ONES[int(d)] for d in frac if d.isdigit()]
    if len(t) > 15:
        return [_ONES[int(d)] for d in t]
    n = int(t)
    if n == 0:
        return ["zero"]
    words: list[str] = []
    for scale, name in _SCALES:
        if n >= scale:
            words += _below_thousand(n // scale) + [name]
            n %= scale
    return words + _below_thousand(n)


# --------------------------------------------------------- syllables
_SINGLES = set("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
               "がぎぐげござじずぜぞだでどばびぶべぼぱぴぷぺぽっ")
_DOUBLES = set(
    "すぃ てゅ てぃ とぅ ふぁ ふぃ ふぇ ふぉ いぇ つぁ つぃ つぇ つぉ うぃ うぇ うぉ ずぃ でゅ でぃ どぅ "
    "きゃ きゅ きぇ きょ しゃ しゅ しぇ しょ ちゃ ちゅ ちぇ ちょ にゃ にゅ にぇ にょ ひゃ ひゅ ひぇ ひょ "
    "みゃ みゅ みぇ みょ りゃ りゅ りぇ りょ ぎゃ ぎゅ ぎぇ ぎょ じゃ じゅ じぇ じょ びゃ びゅ びぇ びょ "
    "ぴゃ ぴゅ ぴぇ ぴょ".split()
)
_BIG = dict(zip("ぁぃぅぇぉゃゅょゎ", "あいうえおやゆよわ"))
_KATA_FIXES = (
    ("ヴァ", "バ"), ("ヴィ", "ビ"), ("ヴェ", "ベ"), ("ヴォ", "ボ"), ("ヴュ", "ビュ"), ("ヴ", "ブ"),
    ("ティュ", "テュ"), ("ディュ", "デュ"), ("フィュ", "ヒュ"), ("フュ", "ヒュ"), ("ヂ", "ジ"), ("ヅ", "ズ"),
    ("クァ", "クア"), ("クィ", "クイ"), ("クェ", "クエ"), ("クォ", "クオ"),
    ("グァ", "グア"), ("グィ", "グイ"), ("グェ", "グエ"), ("グォ", "グオ"), ("ヵ", "カ"), ("ヶ", "ケ"),
)


def phonetic(kana: str) -> str:
    """Katakana (with ' marks) -> hiragana notation syllables every engine takes.
    Hiragana also lets the engine devoice vowels itself (て_すと)."""
    for old, new in _KATA_FIXES:
        kana = kana.replace(old, new)
    hira = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in kana)
    out: list[str] = []
    i = 0
    while i < len(hira):
        two = hira[i : i + 2]
        if two in _DOUBLES:
            out.append(two)
            i += 2
            continue
        ch = hira[i]
        if ch in _SINGLES or ch in "ー'":
            out.append(ch)
        elif ch in _BIG:
            out.append(_BIG[ch])
        i += 1
    return "".join(out)


def clean_phrase(phrase: str) -> str:
    """Drop the sequences the player rejects (error 2012): ー at the start of a
    phrase, っっ, っー; and a stray leading accent mark."""
    phrase = re.sub("っ{2,}", "っ", phrase)
    phrase = re.sub("っー+", "っ", phrase)
    return phrase.lstrip("ー'")


# ------------------------------------------------------------ phrases
def _phrase(parts: list[tuple[Reading, bool]]) -> str:
    out: list[str] = []
    for reading, accented in parts:
        k = reading.kana
        if accented and reading.accent is not None:
            k = k[: reading.accent] + "'" + k[reading.accent :]
        out.append(k)
    return clean_phrase(phonetic("".join(out)))


def _group(words: list[str]) -> list[str]:
    """One accent phrase per content word; function words lean forward onto
    the next content word, or back onto the last one at the end of a clause."""
    phrases: list[list[tuple[Reading, bool]]] = []
    pending: list[tuple[Reading, bool]] = []
    for w in words:
        r = word_reading(w)
        if not r.kana:
            continue
        if w.lower() in FUNCTION_WORDS:
            pending.append((r, False))
            continue
        phrases.append(pending + [(r, True)])
        pending = []
    if pending:
        if phrases:
            phrases[-1].extend(pending)
        else:
            phrases.append(pending)
    return [p for p in map(_phrase, phrases) if p]


def to_notation(text: str) -> str | None:
    """The whole text as one "#>" notation string, or None when it holds
    Japanese (the normal reader handles that) or nothing readable."""
    if not text or _JAPANESE.search(text):
        return None
    out: list[str] = []
    clause: list[str] = []

    def flush(sep: str) -> None:
        phrases = _group(clause)
        clause.clear()
        if phrases:
            out.append("/".join(phrases) + sep)
        elif out and sep != "、" and out[-1].endswith("、"):
            out[-1] = out[-1][:-1] + sep

    for m in _TOKEN.finditer(text):
        kind = m.lastgroup
        tok = m.group(kind)
        if kind == "word":
            clause.extend(split_word(tok))
        elif kind == "num":
            clause.extend(number_words(tok))
        elif kind == "sym":
            clause.append(_SYMBOL_WORDS[tok])
        elif kind == "pause":
            flush("、")
        else:
            flush("？" if "?" in tok else "。")
    flush("。")
    return "#>" + "".join(out) if out else None


def to_plain(notation: str) -> str:
    """Notation back to plain katakana, for when the player rejects it."""
    s = notation[2:] if notation.startswith("#>") else notation
    s = re.sub(r"[/+;]", " ", s.replace("'", ""))
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def is_aquestalk_voice(voice: str | None) -> bool:
    return bool(voice) and "AquesTalkPlayer" in voice
