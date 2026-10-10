"""English -> katakana transliteration, so the yukkuri voice reads English
words with a Japanese accent ("All tests passed" -> オール テスツ パスト).

Resolution order per word: OVERRIDES (project jargon and words the rules get
wrong) -> the JMdict loanword table (standard spellings: センテンス, レビュー)
-> an inflection of either (センテンシズ, レビュード) -> CMU pronouncing
dictionary + ARPAbet->kana rules -> acronym / too-short -> letter names ->
romaji-style reading of the spelling. word_reading() also says where the
English primary stress falls in the kana, for the accent-marked AquesTalk
notation (claude_talk.notation). Everything that is not a Latin-letter run
(Japanese, digits, symbols) is left alone; ASCII sentence punctuation becomes
its Japanese counterpart. Pure Python; cmudict (~1 MB) is loaded lazily.
"""
from __future__ import annotations

import difflib
import logging
import re
from functools import lru_cache
from typing import NamedTuple

from . import loanwords

log = logging.getLogger("claude_talk")


class Reading(NamedTuple):
    kana: str
    accent: int | None  # index in `kana` just after the stressed mora; None = no stress

_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z']*")
_HYPHEN_SPLIT = re.compile(r"-+")

# ----------------------------------------------------------------- tables
OVERRIDES: dict[str, str] = {
    # project / tooling jargon the dictionary lacks or the rules mangle
    "claude": "クロード", "talk": "トーク", "pytest": "パイテスト", "python": "パイソン",
    "json": "ジェイソン", "yaml": "ヤムル", "git": "ギット", "mcp": "エムシーピー",
    "api": "エーピーアイ", "gpu": "ジーピーユー", "cpu": "シーピーユー", "ok": "オーケー",
    "okay": "オーケー", "really": "リアリー", "finished": "フィニッシュド", "finish": "フィニッシュ",
    "error": "エラー", "errors": "エラーズ", "log": "ログ", "logs": "ログズ", "file": "ファイル",
    "files": "ファイルズ", "server": "サーバー", "model": "モデル", "models": "モデルズ",
    "data": "データ", "update": "アップデート", "updated": "アップデーテッド",
    "install": "インストール", "installed": "インストールド", "restart": "リスタート",
    "session": "セッション", "sessions": "セッションズ", "check": "チェック", "please": "プリーズ",
    "ready": "レディ", "done": "ダン", "complete": "コンプリート", "completed": "コンプリーテッド",
    "failed": "フェイルド", "passed": "パスト", "warning": "ワーニング", "warnings": "ワーニングズ",
    "timeout": "タイムアウト", "network": "ネットワーク", "proxy": "プロキシ", "config": "コンフィグ",
    "script": "スクリプト", "scripts": "スクリプツ", "question": "クエスチョン", "answer": "アンサー",
    "input": "インプット", "output": "アウトプット", "voice": "ボイス", "yukkuri": "ゆっくり",
    "hello": "ハロー", "hi": "ハイ", "thanks": "サンクス", "sorry": "ソーリー", "kevin": "ケビン",
    "windows": "ウィンドウズ", "linux": "リナックス", "docker": "ドッカー", "html": "エイチティーエムエル",
    "pc": "ピーシー", "wav": "ワブ", "quant": "クウォント", "auto": "オート", "commit": "コミット",
    "push": "プッシュ", "pull": "プル", "merge": "マージ", "branch": "ブランチ", "test": "テスト",
    "tests": "テスツ", "build": "ビルド", "download": "ダウンロード", "all": "オール",
    "the": "ザ", "a": "ア", "an": "アン", "is": "イズ", "are": "アー", "and": "アンド", "or": "オア",
    "of": "オブ", "to": "トゥ", "for": "フォー", "with": "ウィズ", "on": "オン", "in": "イン",
    "it": "イット", "this": "ディス", "that": "ザット", "you": "ユー", "your": "ユア", "i": "アイ",
    "me": "ミー", "my": "マイ", "we": "ウィー", "now": "ナウ", "here": "ヒア", "there": "ゼア",
    "yes": "イェス", "no": "ノー", "not": "ノット", "new": "ニュー", "one": "ワン", "two": "トゥー",
    "three": "スリー", "need": "ニード", "needs": "ニーズ", "wait": "ウェイト", "waiting": "ウェイティング",
    "blocked": "ブロックド", "attention": "アテンション", "look": "ルック", "see": "シー",
    "moment": "モーメント", "minute": "ミニット", "minutes": "ミニッツ", "result": "リザルト",
    "results": "リザルツ", "message": "メッセージ", "progress": "プログレス", "process": "プロセス",
    "running": "ランニング", "started": "スターテッド", "stopped": "ストップド", "report": "レポート",
    # the table's pick or the rules miss the usual spelling
    "query": "クエリー", "window": "ウィンドウ", "today": "トゥデイ", "tomorrow": "トゥモロー",
    "dataset": "データセット", "backtest": "バックテスト", "java": "ジャバ", "py": "パイ",
    "four": "フォー", "year": "イヤー", "years": "イヤーズ", "hmm": "フーム", "civ": "シブ",
    "language": "ランゲージ", "from": "フロム", "capital": "キャピタル",
}

LETTERS: dict[str, str] = {
    "a": "エー", "b": "ビー", "c": "シー", "d": "ディー", "e": "イー", "f": "エフ", "g": "ジー",
    "h": "エイチ", "i": "アイ", "j": "ジェー", "k": "ケー", "l": "エル", "m": "エム", "n": "エヌ",
    "o": "オー", "p": "ピー", "q": "キュー", "r": "アール", "s": "エス", "t": "ティー", "u": "ユー",
    "v": "ブイ", "w": "ダブリュー", "x": "エックス", "y": "ワイ", "z": "ゼット",
}

# ARPAbet vowel -> kana; the first kana picks the consonant column
VOWELS: dict[str, str] = {
    "AA": "オ", "AE": "ア", "AH": "ア", "AO": "オ", "AW": "アウ", "AY": "アイ", "EH": "エ",
    "ER": "アー", "EY": "エイ", "IH": "イ", "IY": "イー", "OW": "オー", "OY": "オイ", "UH": "ウ",
    "UW": "ウー",
}
_COL = {"ア": 0, "イ": 1, "ウ": 2, "エ": 3, "オ": 4}
ROWS: dict[str, tuple[str, str, str, str, str]] = {
    "K": ("カ", "キ", "ク", "ケ", "コ"), "G": ("ガ", "ギ", "グ", "ゲ", "ゴ"),
    "S": ("サ", "シ", "ス", "セ", "ソ"), "Z": ("ザ", "ジ", "ズ", "ゼ", "ゾ"),
    "T": ("タ", "ティ", "トゥ", "テ", "ト"), "D": ("ダ", "ディ", "ドゥ", "デ", "ド"),
    "N": ("ナ", "ニ", "ヌ", "ネ", "ノ"), "HH": ("ハ", "ヒ", "フ", "ヘ", "ホ"),
    "B": ("バ", "ビ", "ブ", "ベ", "ボ"), "P": ("パ", "ピ", "プ", "ペ", "ポ"),
    "M": ("マ", "ミ", "ム", "メ", "モ"), "R": ("ラ", "リ", "ル", "レ", "ロ"),
    "L": ("ラ", "リ", "ル", "レ", "ロ"), "Y": ("ヤ", "イ", "ユ", "イェ", "ヨ"),
    "W": ("ワ", "ウィ", "ウ", "ウェ", "ウォ"), "F": ("ファ", "フィ", "フ", "フェ", "フォ"),
    "V": ("バ", "ビ", "ブ", "ベ", "ボ"), "TH": ("サ", "シ", "ス", "セ", "ソ"),
    "DH": ("ザ", "ジ", "ズ", "ゼ", "ゾ"), "SH": ("シャ", "シ", "シュ", "シェ", "ショ"),
    "ZH": ("ジャ", "ジ", "ジュ", "ジェ", "ジョ"), "CH": ("チャ", "チ", "チュ", "チェ", "チョ"),
    "JH": ("ジャ", "ジ", "ジュ", "ジェ", "ジョ"), "NG": ("ンガ", "ンギ", "ング", "ンゲ", "ンゴ"),
}
CODA: dict[str, str] = {
    "K": "ク", "G": "グ", "S": "ス", "Z": "ズ", "T": "ト", "D": "ド", "N": "ン", "M": "ン",
    "NG": "ング", "HH": "", "B": "ブ", "P": "プ", "R": "ー", "L": "ル", "F": "フ", "V": "ブ",
    "TH": "ス", "DH": "ズ", "SH": "シュ", "ZH": "ジュ", "CH": "チ", "JH": "ジ", "Y": "イ", "W": "ウ",
}
# consonant + Y + vowel -> consonant's イ column + small kana
PALATAL: dict[str, str] = {"UW": "ュー", "UH": "ュ", "AA": "ョ", "AH": "ャ", "AO": "ョ", "OW": "ョー", "AW": "ャウ"}
SHORT = {"AE", "AH", "EH", "IH", "UH", "AA", "AO"}
STOPS = {"K", "T", "P"}


def has_latin(text: str) -> bool:
    return bool(text) and _LATIN_RUN.search(text) is not None


def _split(phone: str) -> tuple[str, str]:
    return (phone[:-1], phone[-1]) if phone and phone[-1].isdigit() else (phone, "")


SMALL_KANA = "ァィゥェォャュョヮ"
SPECIAL_MORA = "ーンッ"  # cannot carry a Japanese accent nucleus


def first_mora_end(kana: str) -> int | None:
    """Index just after the first mora that can carry an accent (skips a
    leading ン etc.; keeps small kana with their mora)."""
    i = 0
    while i < len(kana):
        j = i + 1
        while j < len(kana) and kana[j] in SMALL_KANA:
            j += 1
        if kana[i] not in SPECIAL_MORA:
            return j
        i = j
    return None


def arpabet_to_kana(phones: list[str]) -> str:
    return _arpabet(phones).kana


def _respell(phones: list[str]) -> list[str]:
    """Phone rewrites that match how Japanese spells English: an r-coloured
    vowel before a vowel lends its r to the next mora (メモリー), and the glide
    into -er after a diphthong becomes ヤ/ワ (プレイヤー, パワー, ワイヤーレス)."""
    out: list[str] = []
    for k, p in enumerate(phones):
        ph, stress = _split(p)
        nxt = _split(phones[k + 1])[0] if k + 1 < len(phones) else None
        prev = _split(out[-1])[0] if out else None
        if ph == "ER" and nxt in VOWELS:
            out += ["AH" + stress, "R"]
        elif ph == "ER" and prev in ("EY", "AY", "OY"):
            out += ["Y", p]
        elif ph == "R" and prev in ("EY", "AY", "OY") and nxt not in VOWELS:
            out += ["Y", "ER0"]
        elif ph == "AW" and nxt == "ER":
            out += ["AH" + stress, "W"]
        else:
            out.append(p)
    return out


# --------------------------------------------- spelling-guided endings
# Japanese loanwords take unstressed vowels from the SPELLING (チョーズン, not
# the schwa's チョーザン). Each rule: spelling suffix, a pattern over the last
# phones, and their replacement. "Q" is a pseudo-phone for ッ, ":" for ー.
def _is_c(p: str) -> bool:
    return _split(p)[0] not in VOWELS


def _schwa(p: str) -> bool:
    return p in ("AH0", "IH0")


def _ph(*names: str):
    return lambda p: _split(p)[0] in names


def _en_vowel(c: str) -> str:
    c = _split(c)[0]
    if c in ("B", "P", "V", "F", "K", "G", "S", "Z"):
        return "UH0"  # トークン, チョーズン, セブン
    if c in ("CH", "JH", "SH", "ZH"):
        return "IH0"  # キッチン
    return "EH0"  # ゴールデン, チルドレン


_ENDINGS = (
    (r"ited", (_is_c, _schwa, _ph("T"), _schwa, _ph("D")), lambda m: [m[0], "IH0", "T", "EH0", "Q", "D"]),
    (r"[td]ed", (_ph("T", "D"), _schwa, _ph("D")), lambda m: [m[0], "EH0", "Q", "D"]),
    (r"et", (_is_c, lambda p: p in ("AH0", "IH0", "EH0", "EH2"), _ph("T")), lambda m: [m[0], "EH0", "Q", "T"]),
    (r"age", (lambda p: _is_c(p) and _split(p)[0] != "W", _schwa, _ph("JH")), lambda m: [m[0], "EH0", ":", "JH"]),
    (r"ate", (_is_c, _schwa, _ph("T")), lambda m: [m[0], "EH0", ":", "T"]),
    (r"[tsxh]ion", (_ph("SH", "ZH", "CH"), _schwa, _ph("N")), lambda m: [m[0], "AO0", "N"]),
    (r"ment", (_ph("M"), _schwa, _ph("N"), _ph("T")), lambda m: ["M", "EH0", "N", "T"]),
    (r"[nl]ess", (_ph("N", "L"), _schwa, _ph("S")), lambda m: [m[0], "EH0", "S"]),
    (r"ful", (_ph("F"), lambda p: p in ("AH0", "IH0", "UH0"), _ph("L")), lambda m: ["F", "UH0", "L"]),
    (r"ible", (_schwa, _ph("B"), _schwa, _ph("L")), lambda m: ["IH0", "B", "L"]),
    (r"able", (_schwa, _ph("B"), _schwa, _ph("L")), lambda m: ["AH0", "B", "L"]),
    (r"[bcdfgkpstz]le", (_is_c, _schwa, _ph("L")), lambda m: [m[0], "L"]),
    (r"el", (_is_c, _schwa, _ph("L")), lambda m: [m[0], "EH0", "L"]),
    (r"ol", (_is_c, _schwa, _ph("L")), lambda m: [m[0], "AO0", "L"]),
    (r"il", (_is_c, _schwa, _ph("L")), lambda m: [m[0], "IH0", "L"]),
    (r"en", (_is_c, _schwa, _ph("N")), lambda m: [m[0], _en_vowel(m[0]), "N"]),
    (r"(?<!i)on", (_is_c, _schwa, _ph("N")), lambda m: [m[0], "UH0" if _split(m[0])[0] == "Z" else "AO0", "N"]),
)
_ENDING_RES = tuple((re.compile(f"(?:{s})$"), pat, rep) for s, pat, rep in _ENDINGS)


def _final_r(low: str, phones: list[str]) -> list[str] | None:
    """Word-final r after a front or rounded vowel is ア: ケア, クリア, シュア,
    and モア/ドア for the -ore/-oor/-oar spellings (but フォー for four)."""
    if len(phones) < 2 or _split(phones[-1])[0] != "R":
        return None
    v, stress = _split(phones[-2])
    if v in ("EH", "UH") or (v == "AO" and re.search(r"(?:ore|oor|oar)$", low)):
        return phones[:-1] + ["AH0"]
    if v in ("IH", "IY"):
        return phones[:-2] + ["IH" + stress, "AH0"]
    return None


def _apply_endings(low: str, phones: list[str]) -> list[str] | None:
    for spelling, pattern, replace in _ENDING_RES:
        k = len(pattern)
        if len(phones) >= k and spelling.search(low) and all(f(p) for f, p in zip(pattern, phones[-k:])):
            return phones[:-k] + replace(phones[-k:])
    return _final_r(low, phones)


def _spelled_phones(low: str, phones: list[str]) -> list[str]:
    """The phones with the spelling-guided endings applied, to the word or,
    for an inflected word, to its stem (levels -> level + s)."""
    out = _apply_endings(low, phones)
    if out is not None:
        return out
    for base in _bases(low):
        bp = _phones(base)
        if bp and len(phones) > len(bp) and _bare(phones[: len(bp)]) == _bare(bp):
            stem = _apply_endings(base, phones[: len(bp)])
            if stem is not None:
                tail = ["IH0" if p == "AH0" else p for p in phones[len(bp):]]
                if _split(bp[-1])[0] == "R" and _split(tail[0])[0] in VOWELS:
                    stem.append("R")  # the r is heard again before a vowel: ヒア+リング
                return stem + tail
    return phones


def _bare(phones: list[str]) -> list[str]:
    return [_split(p)[0] for p in phones]


def _arpabet(phones: list[str]) -> Reading:
    phones = _respell(phones)
    out: list[str] = []
    accent: int | None = None
    after_short_stressed = False  # for the small ッ before a final voiceless stop
    i, n = 0, len(phones)

    def at(k: int) -> str | None:
        return _split(phones[k])[0] if k < n else None

    def voiced(chunk: str, stress: str) -> None:
        nonlocal accent
        if stress == "1" and accent is None:
            end = first_mora_end(chunk)
            if end is not None:
                accent = sum(map(len, out)) + end
        out.append(chunk)

    def vowel_at(k: int) -> str:
        v = _split(phones[k])[0]
        if v == "AA" and at(k + 1) == "R" and at(k + 2) not in VOWELS:
            return "ア"  # "ar" + consonant/end is アー (カー, スタート), not オー
        return VOWELS[v]

    while i < n:
        ph, stress = _split(phones[i])
        if ph in VOWELS:
            voiced(vowel_at(i), stress)
            after_short_stressed = ph in SHORT and stress == "1"
            i += 1
            continue
        nxt, nxt2 = at(i + 1), at(i + 2)
        if nxt == "Y" and nxt2 in PALATAL and ph in ROWS and ph not in ("Y", "W"):
            voiced(ROWS[ph][1] + PALATAL[nxt2], _split(phones[i + 2])[1])
            after_short_stressed = False
            i += 3
            continue
        if nxt in VOWELS and ph in ROWS:
            vowel = vowel_at(i + 1)
            v_stress = _split(phones[i + 1])[1]
            voiced(ROWS[ph][_COL[vowel[0]]] + vowel[1:], v_stress)
            after_short_stressed = nxt in SHORT and v_stress == "1"
            i += 2
            continue
        # coda consonant
        if ph == "K" and nxt == "W" and nxt2 in VOWELS:
            out.append("ク")  # kw + vowel: ク + the bare vowel (リクエスト, クイック)
            after_short_stressed = False
            i += 2
            continue
        if ph == "D" and nxt == "Z" and nxt2 not in VOWELS:
            i += 1  # -ds is ズ (ワーズ), as -ts is ツ
            continue
        if ph == "Q":
            out.append("ッ")  # pseudo-phones from the spelling rules
        elif ph == ":":
            out.append("ー")
        elif ph == "NG" and nxt in ("K", "G"):
            out.append("ン")
        elif ph == "M":
            out.append("ン" if nxt in ("P", "B") else "ム")
        elif ph == "T" and nxt == "S" and at(i + 2) not in VOWELS:
            out.append("ッツ" if after_short_stressed else "ツ")
            i += 1
        elif ph == "R":
            if out and out[-1][-1] not in "ーン":
                out.append("ー")
        elif ph in STOPS and after_short_stressed and nxt not in VOWELS:
            out.append("ッ" + CODA[ph])
        else:
            out.append(CODA.get(ph, ""))
        after_short_stressed = False
        i += 1
    return Reading("".join(out), accent)


@lru_cache(maxsize=1)
def _cmudict() -> dict:
    try:
        import cmudict
    except ImportError:  # pragma: no cover - dictionary optional
        log.warning("cmudict not installed; English words fall back to romaji reading")
        return {}
    return cmudict.dict()


def warm() -> None:
    _cmudict()


def spell_letters(word: str) -> str:
    return "".join(LETTERS.get(ch, "") for ch in word.lower())


# -------------------------------------------------------- romaji fallback
_R_DIGRAPH = {"ch": "CH", "sh": "SH", "th": "TH", "ph": "F", "ts": "TS"}
_R_CONS = {
    "k": "K", "g": "G", "s": "S", "z": "Z", "t": "T", "d": "D", "n": "N", "h": "HH", "b": "B",
    "p": "P", "m": "M", "r": "R", "l": "L", "y": "Y", "w": "W", "f": "F", "v": "V", "j": "JH",
    "q": "K", "x": "KS", "c": "K",
}
_R_VOWEL = {"a": "ア", "i": "イ", "u": "ウ", "e": "エ", "o": "オ"}
_TSU_ROW = ("ツァ", "チ", "ツ", "ツェ", "ツォ")


def romaji_to_kana(word: str) -> str:
    """Read the spelling as if it were romaji: 'conda' -> コンダ, 'numpy' -> ヌンピ."""
    w = word.lower()
    out: list[str] = []
    i, n = 0, len(w)
    while i < n:
        ch = w[i]
        if ch in _R_VOWEL:
            out.append(_R_VOWEL[ch])
            i += 1
            continue
        if ch == "y" and (i + 1 >= n or w[i + 1] not in _R_VOWEL):
            out.append("イ")  # 'py' -> ピ handled below; bare y reads as i
            i += 1
            continue
        # consonant (digraph first)
        cons = _R_DIGRAPH.get(w[i : i + 2])
        step = 2 if cons else 1
        if cons is None:
            cons = _R_CONS.get(ch)
            if cons is None:
                i += 1
                continue
            if ch == "c" and i + 1 < n and w[i + 1] in "ei":
                cons = "S"
        j = i + step
        if cons == "KS":  # x
            out.append("クス")
            i = j
            continue
        if cons == "TS":
            vowel = w[j] if j < n and w[j] in _R_VOWEL else "u"
            out.append(_TSU_ROW[_COL[_R_VOWEL[vowel]]])
            i = j + (1 if j < n and w[j] in _R_VOWEL else 0)
            continue
        # doubled consonant -> small tsu
        if j < n and w[j] == ch and ch not in "nm":
            out.append("ッ")
            i = j
            continue
        if j < n and w[j] in _R_VOWEL:
            out.append(ROWS[cons][_COL[_R_VOWEL[w[j]]]])
            i = j + 1
            continue
        if j < n and w[j] == "y" and j + 1 < n and w[j + 1] in _R_VOWEL and cons not in ("Y", "W"):
            small = {"a": "ャ", "u": "ュ", "o": "ョ", "i": "ィ", "e": "ェ"}[w[j + 1]]
            out.append(ROWS[cons][1] + small)
            i = j + 2
            continue
        if j < n and w[j] == "y":  # 'py' at word end or before a consonant -> ピ
            out.append(ROWS[cons][1])
            i = j + 1
            continue
        # consonant with no vowel
        if cons in ("N", "M"):
            out.append("ン")
        elif cons == "R" or cons == "L":
            out.append("ル")
        elif cons in ("T", "D"):
            out.append(CODA[cons])
        else:
            out.append(CODA.get(cons, ""))
        i = j
    return "".join(out)


# ------------------------------------------------------------- word level
def _loanwords() -> dict[str, str]:
    return loanwords.table()


def _phones(low: str) -> list[str] | None:
    d = _cmudict()
    prons = d.get(low) or d.get(low.replace("'", ""))
    return prons[0] if prons else None


def rule_kana(word: str) -> str | None:
    """The pronunciation-rule reading of a dictionary word, None if unknown."""
    low = word.lower()
    phones = _phones(low)
    return arpabet_to_kana(_spelled_phones(low, phones)) if phones else None


def _fixed(low: str) -> str | None:
    return OVERRIDES.get(low) or _loanwords().get(low)


def _carry(src: str, accent: int, dst: str) -> int | None:
    """Move an accent index from one spelling of a word to another
    (カンピュ'ーター -> コンピュ'ーター) by aligning the two kana strings."""
    pos = len(dst)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, src, dst, autojunk=False).get_opcodes():
        if i1 <= accent <= i2 and (accent < i2 or tag == "equal"):
            pos = j1 + (accent - i1 if tag == "equal" else round((accent - i1) * (j2 - j1) / max(1, i2 - i1)))
            break
    pos = max(0, min(pos, len(dst)))
    while pos < len(dst) and dst[pos] in SMALL_KANA:
        pos += 1  # never split ピュ
    while pos > 1 and dst[pos - 1] in SPECIAL_MORA:
        pos -= 1  # the nucleus sits on the mora before ー/ン/ッ
    return pos if pos > 0 else first_mora_end(dst)


def _spelled(clean: str) -> Reading:
    """Letter names, stressed on the last letter as in English (em-see-PEE)."""
    head = spell_letters(clean[:-1])
    last = spell_letters(clean[-1:])
    end = first_mora_end(last)
    return Reading(head + last, len(head) + end if end else None)


def _accent_for(kana: str, low: str, rule: Reading | None) -> int | None:
    if rule is not None:
        return _carry(rule.kana, rule.accent, kana) if rule.accent is not None else None
    if kana == spell_letters(low):
        return _spelled(low).accent
    return first_mora_end(kana)


_SUFFIXES = (("'s", ""), ("ies", "y"), ("ied", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("d", ""), ("ing", ""), ("ing", "e"))


def _bases(low: str):
    for suffix, add in _SUFFIXES:
        if low.endswith(suffix) and len(low) - len(suffix) >= 2:
            stem = low[: -len(suffix)]
            yield stem + add
            if suffix in ("ed", "ing") and len(stem) > 2 and stem[-1] == stem[-2]:
                yield stem[:-1]  # running -> run


def _inflected(low: str, phones: list[str] | None) -> Reading | None:
    """'sentences' from 'sentence' (センテンス -> センテンシズ): keep the fixed
    spelling of the base; its last consonant mora is re-read together with the
    ending (アタッ+キング, テス+ツ, コミッ+テッド), a vowel-final base just gets
    the ending (レビュー+ズ)."""
    if not phones:
        return None
    for base in _bases(low):
        fixed = _fixed(base)
        bp = _phones(base)
        if not fixed or not bp or len(phones) <= len(bp) or _bare(phones[: len(bp)]) != _bare(bp):
            continue
        # unstressed plural/past vowel: Japanese writes イ (チェンジズ, not チェンジャズ)
        tail = ["IH0" if p == "AH0" else p for p in phones[len(bp):]]
        last = _split(bp[-1])[0]
        if last in VOWELS:
            kana = fixed + arpabet_to_kana(tail)
        else:
            joined = [bp[-1]] + tail
            ending = arpabet_to_kana(_apply_endings(low, joined) or joined)
            own = "" if last == "R" else arpabet_to_kana([bp[-1]])  # R left only a ー/ア behind
            if own and not fixed.endswith(own):
                continue
            head = fixed[: len(fixed) - len(own)]
            before = _split(bp[-2])[1] if len(bp) > 1 else ""
            if head.endswith("ッ") and before == "0" and ending[:1] not in SPECIAL_MORA:
                head = head[:-1]  # ED-it-ed: no doubled t after an unstressed vowel (エディテッド)
            kana = head + ending
        base_reading = word_reading(base)
        accent = base_reading.accent
        return Reading(kana, accent if accent and accent <= len(kana) else None)
    return None


_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_CAPS_WORDS = {"ok"}  # short all-caps words that are not read letter by letter


def split_word(token: str) -> list[str]:
    """ModuleNotFoundError -> Module Not Found Error; hyphens split too."""
    return [p for part in _HYPHEN_SPLIT.split(token) for p in _CAMEL.split(part) if p]


def word_reading(word: str) -> Reading:
    base = word.strip("'")
    if not base:
        return Reading("", None)
    low = base.lower()
    if base.isupper() and 2 <= len(base) <= 3 and low not in _CAPS_WORDS:
        return _spelled(low)  # PR, IT: letters, even if the dictionary has a word
    phones = _phones(low)
    rule = _arpabet(_spelled_phones(low, phones)) if phones else None
    fixed = _fixed(low)
    if fixed:
        return Reading(fixed, _accent_for(fixed, low, rule))
    inflected = _inflected(low, phones)
    if inflected:
        return inflected
    if low.endswith("'s") and _fixed(low[:-2]):  # the dictionary lacks this 's form
        stem = word_reading(low[:-2])
        return Reading(stem.kana + "ズ", stem.accent)
    if rule:
        return rule
    clean = low.replace("'", "")
    if (base.isupper() and len(clean) <= 5) or len(clean) <= 3:
        return _spelled(clean)
    kana = romaji_to_kana(clean)
    return Reading(kana, first_mora_end(kana))


def word_to_kana(word: str) -> str:
    return word_reading(word).kana


def transliterate(text: str) -> str:
    """Replace every Latin-letter run with its katakana reading; convert ASCII
    sentence punctuation; leave Japanese, digits and everything else alone."""
    if not has_latin(text):
        return text

    def repl(m: re.Match[str]) -> str:
        return " ".join(word_to_kana(p) for p in split_word(m.group(0)))

    out = _LATIN_RUN.sub(repl, text)
    out = re.sub(r"-(?=\S)", " ", out)  # hyphens between runs were split above
    out = re.sub(r"(?<=\S)\.(?=\s|$)", "。", out)
    out = re.sub(r",(?=\s|$)", "、", out)
    out = out.replace("!", "！").replace("?", "？")
    return out
