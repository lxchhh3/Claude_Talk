"""Standard Japanese spellings of English loanwords (センテンス, not the
pronunciation-rule guess センタンス), mined from JMdict.

JMdict (EDRDG, CC BY-SA 4.0) lists katakana words with English glosses, but a
gloss is a meaning, not necessarily the source word (マンション is glossed
"apartment"). So a (word, katakana) pair is kept only when its consonant
skeleton matches the rule-based reading of the English word: vowels and
length marks may differ (that is the whole point), consonants may not.

scripts/build_loanwords.py runs this over JMdict_e.gz and writes
claude_talk/data/loanwords.tsv; at run time only load_table()/table() are used.
"""
from __future__ import annotations

import difflib
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from typing import BinaryIO, Callable, Iterable, Iterator

log = logging.getLogger("claude_talk")

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "loanwords.tsv")

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_KATAKANA_WORD = re.compile(r"[ァ-ヴー]+")
_HIRAGANA = re.compile(r"[ぁ-ゖ]")
_ENGLISH_WORD = re.compile(r"[a-z][a-z']*")
_PAREN = re.compile(r"\s*\([^)]*\)")
_LEADING = re.compile(r"^(?:to|a|an|the)\s+")


@dataclass
class Entry:
    readings: list[tuple[str, bool]]  # (katakana, marked common in JMdict)
    words: list[str]  # candidate English source words
    native: bool = False  # a Japanese word (it has a hiragana reading too)


def _single_word(text: str) -> str | None:
    t = _PAREN.sub("", text).strip().lower()
    t = _LEADING.sub("", t)
    return t if _ENGLISH_WORD.fullmatch(t) else None


def _entry(elem: ET.Element) -> Entry | None:
    # Kanji spellings are allowed: a katakana reading under 頁 is still the
    # loanword (ページ). A hiragana reading anywhere marks a native word whose
    # katakana form is just a variant (綺麗: きれい/キレイ "clear").
    native = any(_HIRAGANA.search(r.findtext("reb") or "") for r in elem.findall("r_ele"))
    readings: list[tuple[str, bool]] = []
    for r in elem.findall("r_ele"):
        reb = (r.findtext("reb") or "").strip()
        if not _KATAKANA_WORD.fullmatch(reb) or r.find("re_inf") is not None:
            continue
        readings.append((reb, r.find("re_pri") is not None))
    if not readings:
        return None
    words: list[str] = []
    for sense in elem.findall("sense"):
        sources = sense.findall("lsource")
        if any(s.get(_XML_LANG, "eng") != "eng" or s.get("ls_wasei") == "y" for s in sources):
            continue  # from another language, or a Japanese coinage
        texts = [s.text or "" for s in sources] + [g.text or "" for g in sense.findall("gloss")]
        for t in texts:
            w = _single_word(t)
            if not w:
                continue
            # suru-verbs are glossed as gerunds ("deploying"); offer the verb too
            stems = [w[:-3], w[:-3] + "e"] if w.endswith("ing") and len(w) > 5 else []
            for cand in [w, *stems]:
                if cand not in words:
                    words.append(cand)
    return Entry(readings, words, native) if words else None


def iter_entries(source: BinaryIO) -> Iterator[Entry]:
    """Loanword-shaped entries of a JMdict XML stream (single-word katakana readings)."""
    for _, elem in ET.iterparse(source, events=("end",)):
        if elem.tag != "entry":
            continue
        e = _entry(elem)
        elem.clear()
        if e is not None:
            yield e


# ------------------------------------------------------------- matching
# consonant class of each mora's first kana; vowels, ー and ッ carry none
_CLASS = {ch: cls for cls, chars in {
    "k": "カキクケコ", "g": "ガギグゲゴ", "s": "サシスセソ", "z": "ザジズゼゾヂヅ",
    "t": "タチツテト", "d": "ダデド", "n": "ナニヌネノン", "h": "ハヒフヘホ", "b": "バビブベボヴ",
    "p": "パピプペポ", "m": "マミムメモ", "y": "ヤユヨ", "r": "ラリルレロ", "w": "ワヰヱヲ",
}.items() for ch in chars}
_SMALL = "ァィゥェォャュョヮ"


def skeleton(kana: str) -> str:
    """The consonant classes of a katakana word: センテンス -> sntns. ウィ/ウェ/ウォ
    count as w and イェ as y, since the rules spell English w/y that way."""
    out: list[str] = []
    for i, ch in enumerate(kana):
        nxt = kana[i + 1] if i + 1 < len(kana) else ""
        if ch == "ウ" and nxt in "ィェォ":
            out.append("w")
        elif ch == "イ" and nxt == "ェ":
            out.append("y")
        elif ch in _CLASS:
            out.append(_CLASS[ch])
    return "".join(out)


_PLAIN_WORD = re.compile(r"[a-z]{2,}(?:'[a-z]+)?")


def _vowel_initial(kana: str) -> bool:
    return kana[:1] in "アイウエオ" and kana[:2] not in ("ウィ", "ウェ", "ウォ", "イェ")


def build_table(
    entries: Iterable[Entry],
    rule_reading: Callable[[str], str | None],
    romaji_reading: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """English word -> katakana for every pair whose skeleton matches the rule
    reading. Several matches: JMdict-common first, then the closest to the rule
    reading, then the shorter. Pairs with nothing to compare (no consonants,
    one letter) or a different onset (vowel vs consonant) are dropped. A native
    Japanese word counts only where the English word is its romaji (sakura)."""
    best: dict[str, tuple[tuple, str]] = {}
    for e in entries:
        if e.native:
            for word in e.words:
                if romaji_reading is not None and _PLAIN_WORD.fullmatch(word):
                    for kana, common in e.readings:
                        if romaji_reading(word) == kana and word not in best:
                            best[word] = ((common, 1.0, -len(kana)), kana)
            continue
        for word in e.words:
            if not _PLAIN_WORD.fullmatch(word):
                continue
            rule = rule_reading(word)
            if not rule:
                continue
            target = skeleton(rule)
            if not target:
                continue
            for kana, common in e.readings:
                if skeleton(kana) != target or kana.endswith("ッ"):
                    continue
                if _vowel_initial(kana) != _vowel_initial(rule):
                    continue
                ratio = difflib.SequenceMatcher(None, kana, rule).ratio()
                key = (common, ratio, -len(kana))
                if word not in best or key > best[word][0]:
                    best[word] = (key, kana)
    return {w: k for w, (_, k) in best.items()}


# ------------------------------------------------------------- the file
def write_table(table: dict[str, str], path: str, header: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in header.splitlines():
            f.write(f"# {line}\n")
        for word in sorted(table):
            f.write(f"{word}\t{table[word]}\n")


def load_table(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            rows = [line.rstrip("\n").split("\t") for line in f if line.strip() and not line.startswith("#")]
    except OSError as exc:
        log.warning("loanword table unavailable (%s); English uses the pronunciation rules only", exc)
        return {}
    return {r[0]: r[1] for r in rows if len(r) == 2}


@lru_cache(maxsize=1)
def table() -> dict[str, str]:
    """The shipped table, loaded once."""
    return load_table(DATA_PATH)
